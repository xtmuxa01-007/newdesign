"""Other cash handovers notify bosses, including unrecorded cash and reversals."""
from decimal import Decimal
import os
import unittest
import uuid

from sqlalchemy import select
import test_branch_archive as fixture
from app.models import Audit


class OtherPaymentNotificationsTest(unittest.TestCase):
    setUp = fixture.BranchArchiveTest.setUp
    tearDown = fixture.BranchArchiveTest.tearDown
    client = fixture.BranchArchiveTest.client

    def payout(self, branch=1, amount='20000'):
        response = self.owner.post('/api/other-payments', json={
            'request_id': str(uuid.uuid4()), 'branch_id': branch, 'amount': amount,
            'method': 'cash', 'recipient': 'Marwa', 'note': 'Dasturga kiritilmagan eski qarz puli topshirildi.'})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_all_bosses_receive_amount_reason_difference_and_independent_read_state(self):
        self.payout()
        other = self.client('boss')
        for boss in (self.owner, other):
            response = boss.get('/api/notifications/changes')
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            self.assertEqual(data['unread_count'], 1)
            entry = data['items'][0]
            self.assertEqual(entry['kind'], 'other_payment')
            self.assertIn('eski qarz puli', entry['reason'])
            self.assertEqual(entry['payment']['recipient'], 'Marwa')
            self.assertEqual(Decimal(entry['payment']['amount']), 20000)
            self.assertEqual(Decimal(entry['payment']['balance_before']), 0)
            self.assertEqual(Decimal(entry['payment']['balance_after']), -20000)
            self.assertEqual(Decimal(entry['payment']['unrecorded_amount']), 20000)
        self.assertEqual(self.owner.post('/api/notifications/changes/read', json={'event_ids': [entry['id']]}).status_code, 200)
        self.assertEqual(self.owner.get('/api/notifications/changes').json()['unread_count'], 0)
        self.assertEqual(other.get('/api/notifications/changes').json()['unread_count'], 1)
        detail = self.owner.get(f"/api/changes/{entry['id']}").json()
        self.assertFalse(detail['unread'])
        self.assertEqual(detail['payment']['amount'], entry['payment']['amount'])

    def test_cancellation_notifies_and_keeps_original_note_snapshot(self):
        payment = self.payout()
        result = self.owner.post(f"/api/operations/other_payment/{payment['id']}/cancel", json={
            'request_id': str(uuid.uuid4()), 'reason': 'Topshiriqda xato bo‘lgan',
            'expected_fingerprint': payment['operation']['expected_fingerprint']})
        self.assertEqual(result.status_code, 200, result.text)
        entries = self.owner.get('/api/notifications/changes').json()['items']
        self.assertEqual([item['kind'] for item in entries], ['other_payment_cancelled', 'other_payment'])
        self.assertTrue(all(item['payment']['cancelled'] for item in entries))
        self.assertIn('xato', entries[0]['reason'])
        self.assertIn('eski qarz puli', entries[0]['payment']['note'])
        self.assertEqual(self.owner.get('/api/changes?kind=other_payment').json()['total'], 1)
        self.assertEqual(self.owner.get('/api/changes?kind=other_payment_cancelled').json()['total'], 1)
        self.assertEqual(self.owner.get('/api/changes?kind=sale_cancelled').json()['total'], 0)

    def test_admin_branch_scope_and_boss_only_notifications(self):
        own = self.payout()
        self.payout(branch=2)
        admin = self.client('admin')
        self.assertEqual(admin.get('/api/changes?kind=other_payment').json()['total'], 1)
        other = next(item for item in self.owner.get('/api/changes?kind=other_payment').json()['items'] if item['branch_id'] == 2)
        self.assertEqual(admin.get(f"/api/changes/{other['id']}").status_code, 403)
        self.assertEqual(admin.get('/api/notifications/changes').status_code, 403)
        self.assertEqual(self.client('cashier').get('/api/notifications/changes').status_code, 403)

    def test_unknown_or_synced_fake_payment_audit_never_becomes_notification(self):
        payment = self.payout()
        with self.sessions() as db:
            entry = db.scalar(select(Audit).where(Audit.action == 'Boshqa pul berildi'))
            db.add_all([
                Audit(user_id=4, actor='Fixture', branch_id=1, action='Boshqa pul berildi',
                      detail={**entry.detail, '_sync_source': {'device_id': 'fake'}}),
                Audit(user_id=4, actor='Fixture', branch_id=1, action='Boshqa pul berildi',
                      detail={'payment_id': 'not-an-integer', 'request_id': 'unknown', 'amount': '20'}),
            ])
            db.commit()
        self.assertEqual(self.owner.get('/api/notifications/changes').json()['unread_count'], 1)


@unittest.skipUnless(os.getenv('CRM_TEST_POSTGRES') == '1', 'Disposable CI PostgreSQL kerak')
class OtherPaymentNotificationsPostgresTest(OtherPaymentNotificationsTest):
    postgres = True


if __name__ == '__main__':
    unittest.main()
