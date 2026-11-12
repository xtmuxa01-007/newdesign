"""Only disposable fixtures: audit feeds never change financial records."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
import unittest
from unittest.mock import patch
import uuid

from sqlalchemy import event, func, select
import test_branch_archive as fixture
import test_operation_cancel as cancellation_fixture
from app.change_events import READ_ACTION
from app.models import Audit, Product, User
from app.stock_prices import PRICE_CHANGE_ACTION


class ChangeEventsTest(unittest.TestCase):
    setUp = fixture.BranchArchiveTest.setUp
    tearDown = fixture.BranchArchiveTest.tearDown
    client = fixture.BranchArchiveTest.client
    sale = fixture.BranchArchiveTest.sale
    create_sale = cancellation_fixture.OperationCancelTest.create_sale
    create_debt_sale = cancellation_fixture.OperationCancelTest.create_debt_sale
    receipt = cancellation_fixture.OperationCancelTest.receipt
    payload = cancellation_fixture.OperationCancelTest.payload
    cancel = cancellation_fixture.OperationCancelTest.cancel

    def price(self, stock_id=1, expected='10000', value='12000', request_id=None):
        body = {'request_id': request_id or str(uuid.uuid4()), 'expected_price': expected,
                'price': value, 'reason': 'Fixture price event reason'}
        response = self.owner.post(f'/api/stocks/{stock_id}/price', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return body

    def append_price(self, branch=1, created=None, id=None):
        """Feed-only fixture with controlled event order/date; stock is untouched."""
        with self.sessions() as db:
            detail = {'stock_id': branch, 'product_id': 1, 'request_id': str(uuid.uuid4()),
                      'before': '10000.00', 'after': '12000.00', 'reason': 'Historical fixture'}
            entry = Audit(user_id=4, actor='Programmist', branch_id=branch,
                          action=PRICE_CHANGE_ACTION, detail=detail)
            if created is not None:
                entry.created_at = created
            if id is not None:
                entry.id = id
            db.add(entry)
            db.commit()
            return entry.id

    def state(self):
        with self.sessions() as db:
            return {table.name: sorted(list(db.execute(select(table))), key=repr)
                    for table in Audit.metadata.sorted_tables}

    def marks(self):
        with self.sessions() as db:
            return [(entry.user_id, entry.detail['event_id']) for entry in db.scalars(
                select(Audit).where(Audit.action == READ_ACTION).order_by(Audit.id))]

    def read(self, ids, client=None):
        return (client or self.owner).post('/api/notifications/changes/read', json={'event_ids': ids})

    def test_only_price_and_whole_sale_cancel_events_have_typed_details(self):
        sold, _ = self.create_sale(mini_discount='1000', cash='9000')
        cancelled = self.cancel('sale', sold['id'])
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.price()
        receipt, _ = self.receipt(price='12000')
        self.assertEqual(self.cancel('receipt', receipt['id']).status_code, 200)
        response = self.owner.get('/api/changes')
        self.assertEqual(response.status_code, 200, response.text)
        feed = response.json()
        self.assertEqual(feed['total'], 2)
        self.assertEqual([item['kind'] for item in feed['items']], ['price_change', 'sale_cancelled'])
        price, sale = feed['items']
        self.assertEqual(price['id'], price['event_id'])
        self.assertEqual((price['branch_id'], price['branch_name'], price['actor']), (1, 'Shared', 'Programmist'))
        self.assertTrue(price['title'])
        self.assertEqual(price['price']['before'], '10000.00')
        self.assertEqual(price['price']['after'], '12000.00')
        self.assertEqual(price['price']['product_id'], 1)
        self.assertNotIn('items', sale['sale'])
        detailed = self.owner.get(f"/api/changes/{sale['id']}").json()
        self.assertEqual((detailed['sale']['id'], detailed['sale']['cashier']), (sold['id'], 'Programmist'))
        self.assertEqual(detailed['sale']['total'], '9000.00')
        self.assertEqual(detailed['sale']['mini_discount'], '1000.00')
        self.assertEqual(detailed['sale']['items'][0], {
            'id': sold['items'][0]['id'], 'name': 'Product', 'sku': 'TEST-1', 'kg': '1.000',
            'price': '10000.00', 'discount': '0.00', 'mini_discount': '1000.00', 'total': '9000.00'})
        self.assertEqual(self.owner.get('/api/changes?kind=price_change').json()['total'], 1)
        self.assertEqual(self.owner.get('/api/changes?kind=sale_cancelled').json()['total'], 1)

    def test_read_only_gets_leave_full_database_unchanged(self):
        sale, _ = self.create_sale()
        self.assertEqual(self.cancel('sale', sale['id']).status_code, 200)
        self.price()
        other = self.client('boss')
        before = self.state()
        response = self.owner.get('/api/changes')
        self.assertEqual(response.status_code, 200, response.text)
        for item in response.json()['items']:
            self.assertEqual(self.owner.get(f"/api/changes/{item['id']}").status_code, 200)
        self.assertEqual(self.owner.get('/api/notifications/changes').json()['unread_count'], 2)
        self.assertEqual(other.get('/api/notifications/changes').json()['unread_count'], 2)
        self.assertEqual(self.state(), before)

    def test_boss_notifications_are_global_and_each_boss_reads_independently(self):
        self.price()
        self.price(stock_id=2)
        other = self.client('boss')
        notifications = self.owner.get('/api/notifications/changes?branch_id=1&limit=1').json()
        self.assertEqual(notifications['unread_count'], 2)
        self.assertEqual(len(notifications['items']), 1)
        self.assertEqual(notifications['items'][0]['branch_id'], 2)
        event_id = notifications['items'][0]['id']
        before = self.state()
        read = self.read([event_id, event_id])
        self.assertEqual(read.status_code, 200, read.text)
        self.assertEqual(read.json(), {'ok': True, 'acknowledged': [event_id], 'unread_count': 1})
        self.assertEqual(self.marks(), [(4, event_id)])
        self.assertEqual(self.read([event_id]).status_code, 200)
        self.assertEqual(self.marks(), [(4, event_id)])
        after = self.state()
        self.assertEqual({key: value for key, value in before.items() if key != Audit.__tablename__},
                         {key: value for key, value in after.items() if key != Audit.__tablename__})
        self.assertEqual(other.get('/api/notifications/changes').json()['unread_count'], 2)
        self.assertEqual(self.owner.get('/api/notifications/changes').json()['items'][0]['branch_id'], 1)
        self.assertFalse(self.owner.get(f'/api/changes/{event_id}').json()['unread'])
        self.assertTrue(other.get(f'/api/changes/{event_id}').json()['unread'])
        self.assertEqual(self.read([event_id], other).status_code, 200)
        self.assertEqual(sorted(self.marks()), [(1, event_id), (4, event_id)])

    def test_late_visible_lower_event_is_not_hidden_by_a_read_watermark(self):
        with self.sessions() as db:
            high = (db.scalar(select(func.max(Audit.id))) or 0) + 100
        self.append_price(id=high)
        self.assertEqual(self.read([high]).json()['unread_count'], 0)
        late = self.append_price(id=high - 1)
        notifications = self.owner.get('/api/notifications/changes').json()
        self.assertEqual(notifications['unread_count'], 1)
        self.assertEqual([item['id'] for item in notifications['items']], [late])

    def test_role_branch_and_non_event_read_restrictions(self):
        own = self.append_price()
        other = self.append_price(branch=2)
        admin, cashier, anonymous = self.client('admin'), self.client('cashier'), self.client()
        self.assertEqual(admin.get('/api/changes').json()['total'], 1)
        self.assertFalse(admin.get('/api/changes').json()['items'][0]['unread'])
        self.assertEqual(admin.get('/api/changes?branch_id=2').status_code, 403)
        self.assertEqual(admin.get(f'/api/changes/{other}').status_code, 403)
        self.assertEqual(admin.get(f'/api/changes/{own}').status_code, 200)
        self.assertFalse(admin.get(f'/api/changes/{own}').json()['unread'])
        for client, status in ((admin, 403), (cashier, 403), (anonymous, 401)):
            self.assertEqual(client.get('/api/notifications/changes').status_code, status)
            self.assertEqual(self.read([own], client).status_code, status)
        self.assertEqual(cashier.get('/api/changes').status_code, 403)
        self.assertEqual(anonymous.get('/api/changes').status_code, 401)
        with self.sessions() as db:
            ordinary = db.scalar(select(Audit.id).where(Audit.action == 'Tizimga kirdi').limit(1))
        self.assertEqual(self.owner.get(f'/api/changes/{ordinary}').status_code, 404)
        self.assertEqual(self.read([own, ordinary]).status_code, 404)
        self.assertEqual(self.read([999999]).status_code, 404)
        self.assertEqual(self.marks(), [])

    def test_untrusted_origin_cannot_acknowledge_and_orphan_cancellations_are_not_events(self):
        valid = self.append_price()
        response = self.owner.post('/api/notifications/changes/read', json={'event_ids': [valid]},
                                   headers={'Origin': 'https://untrusted.invalid'})
        self.assertEqual(response.status_code, 403, response.text)
        with self.sessions() as db:
            for detail in ({'kind': 'sale', 'operation_id': 999, 'cancellation_id': 999999},
                           {'kind': 'expense', 'operation_id': 1}, {}):
                db.add(Audit(user_id=4, actor='Programmist', branch_id=1,
                             action='Amal bekor qilindi', detail=detail))
            db.commit()
        feed = self.owner.get('/api/changes').json()
        self.assertEqual(feed['total'], 1)
        self.assertEqual(feed['items'][0]['id'], valid)
        self.assertEqual(self.marks(), [])

    def test_imported_audits_cannot_forge_global_read_marks_or_central_events(self):
        valid = self.append_price()
        with self.sessions() as db:
            source = {'device_id': 'untrusted-legacy-device', 'table': 'audit_logs', 'id': 9}
            db.add_all([
                Audit(user_id=4, actor='Spoofed reader', branch_id=1, action=READ_ACTION,
                      detail={'event_id': valid, '_sync_source': source}),
                Audit(user_id=4, actor='Branch reader', branch_id=1, action=READ_ACTION,
                      detail={'event_id': valid}),
                Audit(user_id=4, actor='Spoofed null-branch reader', branch_id=None, action=READ_ACTION,
                      detail={'event_id': valid, '_sync_source': source}),
                Audit(user_id=4, actor='Malformed reader', branch_id=1, action=READ_ACTION,
                      detail={'event_id': 'not-an-integer', '_sync_source': source}),
                Audit(user_id=4, actor='Malformed cancellation', branch_id=1,
                      action='Amal bekor qilindi', detail={'kind': 'sale',
                          'cancellation_id': 'not-an-integer', 'operation_id': {'bad': 'id'},
                          '_sync_source': source}),
                Audit(user_id=4, actor='Spoofed price editor', branch_id=1, action=PRICE_CHANGE_ACTION,
                      detail={'product_id': 1, 'stock_id': 1, 'before': '10000', 'after': '1',
                              '_sync_source': source})])
            db.commit()
        notifications = self.owner.get('/api/notifications/changes').json()
        self.assertEqual(notifications['unread_count'], 1)
        self.assertEqual([item['id'] for item in notifications['items']], [valid])
        self.assertTrue(self.owner.get(f'/api/changes/{valid}').json()['unread'])
        self.assertEqual(self.owner.get('/api/changes').json()['total'], 1)
        self.assertEqual(self.read([valid]).json()['unread_count'], 0)
        sale, _ = self.create_sale()
        self.assertEqual(self.cancel('sale', sale['id']).status_code, 200)
        canonical = self.owner.get('/api/changes?kind=sale_cancelled').json()['items'][0]['id']
        with self.sessions() as db:
            detail = dict(db.get(Audit, canonical).detail, _sync_source=source)
            db.add(Audit(user_id=4, actor='Spoofed cancellation', branch_id=1,
                         action='Amal bekor qilindi', detail=detail))
            db.commit()
        notifications = self.owner.get('/api/notifications/changes').json()
        self.assertEqual(notifications['unread_count'], 1)
        self.assertEqual([item['id'] for item in notifications['items']], [canonical])
        self.assertEqual(self.owner.get('/api/changes').json()['total'], 2)

    def test_tashkent_dates_kind_pagination_and_validation(self):
        dates = [datetime(2026, 9, 30, 18, 59, tzinfo=timezone.utc),
                 datetime(2026, 9, 30, 19, 0, tzinfo=timezone.utc),
                 datetime(2026, 10, 1, 18, 59, tzinfo=timezone.utc),
                 datetime(2026, 10, 1, 19, 0, tzinfo=timezone.utc)]
        ids = [self.append_price(created=value) for value in dates]
        first = self.owner.get('/api/changes?start=2026-10-01&end=2026-10-01&limit=1').json()
        self.assertEqual((first['total'], first['has_more']), (2, True))
        self.assertEqual(first['items'][0]['id'], ids[2])
        second = self.owner.get('/api/changes?start=2026-10-01&end=2026-10-01&limit=1&offset=1').json()
        self.assertEqual(second['items'][0]['id'], ids[1])
        self.assertFalse(second['has_more'])
        for query in ('start=2026-10-02&end=2026-10-01', 'end=9999-12-31',
                      'offset=-1', 'limit=0', 'limit=101', 'kind=receipt'):
            self.assertEqual(self.owner.get('/api/changes?' + query).status_code, 422, query)
        self.assertEqual(self.owner.get('/api/notifications/changes?limit=51').status_code, 422)
        for body in ({'event_ids': []}, {'event_ids': [True]}, {'event_ids': [-1]},
                     {'event_ids': [ids[0]] * 101}, {'event_ids': [ids[0]], 'user_id': 1}):
            response = self.owner.post('/api/notifications/changes/read', json=body)
            self.assertEqual(response.status_code, 422, response.text)
        with patch.dict(os.environ, {'CRM_BRANCH_ID': '1'}):
            self.assertEqual(self.owner.get('/api/notifications/changes').status_code, 409)
            self.assertEqual(self.read([ids[0]]).status_code, 409)
        self.assertEqual(self.marks(), [])

    def test_retries_and_rolled_back_cancellations_do_not_create_extra_events(self):
        sale, _ = self.create_sale()
        price = self.price()
        retry = self.owner.post('/api/stocks/1/price', json=price)
        self.assertEqual(retry.status_code, 200, retry.text)
        expense = self.owner.post('/api/expenses', json={
            'request_id': str(uuid.uuid4()), 'branch_id': 1, 'supplier_id': 1,
            'amount': '5000', 'method': 'cash', 'reason': 'Fixture spent sale cash'})
        self.assertEqual(expense.status_code, 201, expense.text)
        body = self.payload('sale', sale['id'])
        self.assertEqual(self.cancel('sale', sale['id'], body).status_code, 409)
        self.assertEqual(self.owner.get('/api/changes').json()['total'], 1)
        self.assertEqual(self.cancel('expense', expense.json()['id']).status_code, 200)
        self.assertEqual(self.cancel('sale', sale['id'], body).status_code, 200)
        self.assertEqual(self.cancel('sale', sale['id'], body).status_code, 200)
        feed = self.owner.get('/api/changes').json()
        self.assertEqual(feed['total'], 2)
        self.assertEqual([item['kind'] for item in feed['items']], ['sale_cancelled', 'price_change'])

    def test_debt_child_cancellation_is_one_sale_event_and_snapshot_survives_renames(self):
        sale, _ = self.create_debt_sale()
        paid = self.owner.post(f"/api/debts/{sale['debt']['id']}/pay", json={
            'request_id': str(uuid.uuid4()), 'cash': '5000', 'card': '3000'})
        self.assertEqual(paid.status_code, 201, paid.text)
        self.assertEqual(self.cancel('sale', sale['id']).status_code, 200)
        with self.sessions() as db:
            db.get(User, 4).name = 'Renamed later'
            product = db.get(Product, 1)
            product.name, product.sku = 'Changed catalog', 'NEW-SKU'
            db.commit()
        feed = self.owner.get('/api/changes').json()
        self.assertEqual(feed['total'], 1)
        detail = self.owner.get(f"/api/changes/{feed['items'][0]['id']}").json()
        self.assertEqual((detail['actor'], detail['sale']['cashier']), ('Programmist', 'Programmist'))
        self.assertEqual((detail['sale']['debt'], detail['sale']['debt_cash'], detail['sale']['debt_card']),
                         ('8000.00', '5000.00', '3000.00'))
        self.assertEqual((detail['sale']['items'][0]['name'], detail['sale']['items'][0]['sku']),
                         ('Product', 'TEST-1'))

    def test_old_price_labels_are_explicit_current_fallback_and_snapshot_labels_are_frozen(self):
        old = self.append_price()
        self.price()
        new = self.owner.get('/api/changes?kind=price_change').json()['items'][0]['id']
        with self.sessions() as db:
            product = db.get(Product, 1)
            product.name, product.sku = 'Current catalog name', 'CURRENT-SKU'
            db.commit()
        old_item = self.owner.get(f'/api/changes/{old}').json()['price']
        new_item = self.owner.get(f'/api/changes/{new}').json()['price']
        self.assertEqual((old_item['name'], old_item['sku'], old_item['labels_source']),
                         ('Current catalog name', 'CURRENT-SKU', 'current_product'))
        self.assertEqual((new_item['name'], new_item['sku'], new_item['labels_source']),
                         ('Product', 'TEST-1', 'snapshot'))

    def test_parallel_read_retries_append_one_marker_per_event_and_account(self):
        id = self.append_price()
        other = self.client()
        login = other.post('/api/auth/login', json={'username': 'abduqodir', 'password': self.secret})
        self.assertEqual(login.status_code, 200, login.text)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda client: self.read([id], client), (self.owner, other)))
        self.assertTrue(all(result.status_code == 200 for result in results))
        self.assertTrue(all(result.json()['unread_count'] == 0 for result in results))
        self.assertEqual(self.marks(), [(4, id)])
        self.assertEqual(self.owner.get('/api/changes').json()['total'], 1)


@unittest.skipUnless(os.getenv('CRM_TEST_POSTGRES') == '1', 'Disposable CI PostgreSQL kerak')
class ChangeEventsPostgresTest(ChangeEventsTest):
    postgres = True

    def test_notification_count_and_items_share_read_only_repeatable_snapshot(self):
        original = self.append_price()
        inserted = []

        def after_count(connection, cursor, statement, parameters, context, many):
            if not inserted and 'count(' in statement.lower() and 'audit_logs' in statement:
                inserted.append(True)
                inserted.append(self.append_price(branch=2))

        event.listen(self.engine, 'after_cursor_execute', after_count)
        try:
            response = self.owner.get('/api/notifications/changes')
        finally:
            event.remove(self.engine, 'after_cursor_execute', after_count)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['unread_count'], 1)
        self.assertEqual([item['id'] for item in response.json()['items']], [original])
        self.assertEqual(self.owner.get('/api/notifications/changes').json()['unread_count'], 2)


if __name__ == '__main__':
    unittest.main()
