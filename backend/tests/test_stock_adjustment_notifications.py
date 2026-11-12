"""Revision kg changes notify every boss without changing independent read state."""
import os
import unittest
import uuid

from sqlalchemy import select
import test_branch_archive as fixture
from app.models import Audit, Product, StockAdjustment
from app.operation_history import source_fingerprint


class StockAdjustmentNotificationsTest(unittest.TestCase):
    setUp = fixture.BranchArchiveTest.setUp
    tearDown = fixture.BranchArchiveTest.tearDown
    client = fixture.BranchArchiveTest.client

    def adjustment(self, stock=1, before='10', after='8.125', client=None, body=None):
        body = body or {'request_id': str(uuid.uuid4()), 'expected_kg': before,
                        'kg': after, 'reason': 'Reviziyada tarozida qayta o‘lchab tuzatildi.'}
        response = (client or self.owner).post(f'/api/stocks/{stock}/adjustments', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json(), body

    def test_admin_revision_has_exact_quantities_reason_snapshot_and_independent_boss_reads(self):
        adjustment, body = self.adjustment(client=self.client('admin'))
        self.adjustment(before='10', after='11.234', stock=2)
        other_boss = self.client('boss')
        for boss in (self.owner, other_boss):
            response = boss.get('/api/notifications/changes')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['unread_count'], 2)
            entry = next(item for item in response.json()['items'] if item['branch_id'] == 1)
            self.assertEqual(entry['kind'], 'stock_adjustment')
            self.assertEqual(entry['actor'], 'admin')
            self.assertEqual(entry['branch_name'], 'Shared')
            self.assertEqual(entry['reason'], body['reason'])
            self.assertEqual((entry['stock']['before'], entry['stock']['after'], entry['stock']['difference']),
                             ('10.000', '8.125', '-1.875'))
            self.assertEqual((entry['stock']['name'], entry['stock']['sku']), ('Product', 'TEST-1'))
            self.assertEqual(entry['stock']['labels_source'], 'snapshot')
        acknowledged = self.owner.post('/api/notifications/changes/read', json={'event_ids': [entry['id']]})
        self.assertEqual(acknowledged.status_code, 200, acknowledged.text)
        self.assertEqual(self.owner.get('/api/notifications/changes').json()['unread_count'], 1)
        self.assertEqual(other_boss.get('/api/notifications/changes').json()['unread_count'], 2)
        with self.sessions() as db:
            product = db.get(Product, 1)
            product.name, product.sku = 'Renamed catalog', 'LATER-SKU'
            db.commit()
        detail = self.owner.get(f"/api/changes/{entry['id']}").json()
        self.assertEqual((detail['stock']['name'], detail['stock']['sku']), ('Product', 'TEST-1'))
        self.assertFalse(detail['unread'])

    def test_filter_branch_auth_and_retries_never_duplicate_revision_notifications(self):
        _, body = self.adjustment()
        response = self.owner.post('/api/stocks/1/adjustments', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        self.adjustment(stock=2, after='11.001')
        feed = self.owner.get('/api/changes?kind=stock_adjustment&limit=1').json()
        self.assertEqual((feed['total'], feed['has_more']), (2, True))
        self.assertEqual(feed['items'][0]['stock']['difference'], '1.001')
        other_id = feed['items'][0]['id']
        admin = self.client('admin')
        self.assertEqual(admin.get('/api/changes?kind=stock_adjustment').json()['total'], 1)
        self.assertEqual(admin.get(f'/api/changes/{other_id}').status_code, 403)
        self.assertEqual(admin.get('/api/notifications/changes').status_code, 403)
        self.assertEqual(self.client('cashier').get('/api/changes?kind=stock_adjustment').status_code, 403)
        self.assertEqual(self.client().get('/api/notifications/changes').status_code, 401)
        self.assertEqual(self.owner.get('/api/changes?kind=price_change').json()['total'], 0)
        self.assertEqual(self.owner.get('/api/notifications/changes').json()['unread_count'], 2)

    def test_forged_synced_malformed_and_wrong_actor_records_are_not_revision_events(self):
        self.adjustment()
        with self.sessions() as db:
            entry = db.scalar(select(Audit).where(Audit.action == 'Ombor qoldig‘i tuzatildi'))
            detail = dict(entry.detail)
            db.add_all([
                Audit(user_id=4, actor='Sync forgery', branch_id=1, action=entry.action,
                      detail={**detail, '_sync_source': {'device_id': 'legacy'}}),
                Audit(user_id=4, actor='Orphan', branch_id=1, action=entry.action,
                      detail={**detail, 'adjustment_id': 999999, 'request_id': 'nonexistent'}),
                Audit(user_id=4, actor='Malformed', branch_id=1, action=entry.action,
                      detail={**detail, 'adjustment_id': 'not-an-integer'}),
                Audit(user_id=4, actor='Wrong branch', branch_id=2, action=entry.action, detail=detail),
                Audit(user_id=2, actor='Wrong actor', branch_id=1, action=entry.action, detail=detail),
            ])
            db.commit()
        response = self.owner.get('/api/notifications/changes')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['unread_count'], 1)
        self.assertEqual(self.owner.get('/api/changes?kind=stock_adjustment').json()['total'], 1)

    def test_cancellation_preserves_original_revision_event_and_old_snapshot_fallback(self):
        adjustment, _ = self.adjustment()
        with self.sessions() as db:
            source = db.get(StockAdjustment, adjustment['id'])
            fingerprint = source_fingerprint(db, 'stock_adjustment', source)
            entry = db.scalar(select(Audit).where(Audit.action == 'Ombor qoldig‘i tuzatildi'))
            event_id = entry.id
            # Existing deployments did not save product labels or stock_id in this audit.
            entry.detail = {key: value for key, value in entry.detail.items()
                            if key not in ('product_name', 'sku', 'stock_id', 'difference')}
            db.commit()
        response = self.owner.post(f"/api/operations/stock_adjustment/{adjustment['id']}/cancel", json={
            'request_id': str(uuid.uuid4()), 'expected_fingerprint': fingerprint,
            'reason': 'Qoldiqni qayta tekshirishda xato topildi.'})
        self.assertEqual(response.status_code, 200, response.text)
        feed = self.owner.get('/api/changes?kind=stock_adjustment').json()
        self.assertEqual(feed['total'], 1)
        entry = self.owner.get(f'/api/changes/{event_id}').json()
        self.assertTrue(entry['stock']['cancelled'])
        self.assertEqual(entry['stock']['labels_source'], 'current_product')
        self.assertEqual((entry['stock']['before'], entry['stock']['after'], entry['stock']['difference']),
                         ('10.000', '8.125', '-1.875'))
        self.assertIn('Reviziyada', entry['reason'])
        self.assertEqual(self.owner.get('/api/notifications/changes').json()['unread_count'], 1)


@unittest.skipUnless(os.getenv('CRM_TEST_POSTGRES') == '1', 'Disposable CI PostgreSQL kerak')
class StockAdjustmentNotificationsPostgresTest(StockAdjustmentNotificationsTest):
    postgres = True


if __name__ == '__main__':
    unittest.main()
