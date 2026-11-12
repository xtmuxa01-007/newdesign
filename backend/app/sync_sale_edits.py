"""Tuzatishni markazda qayta hisoblash: filial yuborgan tayyor pulga ishonilmaydi."""
from copy import deepcopy
from sqlalchemy import event, select
from .models import Sale, SaleItem, SaleEdit, User, Audit, MiniDiscountShare
from .schemas import EditSale
from .sale_edits import apply_edit
from .common import row
from .sync_projection import MODELS, LOCAL_REFS, identity, remember, typed_row, fail


def apply_edit_bundle(db, device, changes):
    final = {}
    inserted = set()
    for c in changes:
        if not isinstance(c, dict) or set(c) != {'table','operation','row'}:
            fail('Tuzatish paketi noto‘g‘ri.')
        model = MODELS.get(c['table'])
        if model is None or c['operation'] not in ('insert','update','delete'):
            fail('Tuzatish amali noto‘g‘ri.')
        values = typed_row(model, c['row'])
        key = (c['table'], values['id'])
        if c['operation'] == 'insert':
            inserted.add(key)
        final[key] = (c['operation'], values)
    edits = [(key, values) for key, (op, values) in final.items() if key[0] == 'sale_edits']
    if len(edits) != 1 or edits[0][0] not in inserted:
        fail('Paket bitta yangi tuzatishdan iborat bo‘lsin.')
    edit_key, raw_edit = edits[0]
    if raw_edit['branch_id'] != device.branch_id:
        fail('Tuzatish boshqa filialga tegishli.')

    def mapped(table, local_id):
        link = identity(db, device.id, table, local_id)
        if not link:
            fail('Tuzatish uchun yozuv mosligi topilmadi: ' + table)
        return link.central_id

    local_sale_id = raw_edit['sale_id']
    sale_id = mapped('sales', local_sale_id)
    sale = db.get(Sale, sale_id)
    if sale is None or sale.branch_id != device.branch_id:
        fail('Savdo boshqa filialga tegishli.')
    command = deepcopy(raw_edit['command'])
    try:
        for item in command['items']:
            item['item_id'] = mapped('sale_items', item['item_id'])
        data = EditSale.model_validate(command)
    except (ValueError, TypeError, KeyError):
        fail('Tuzatish so‘rovi noto‘g‘ri.')
    db.flush()
    expected = {}

    def capture(session, context):
        for operation, objects in (('insert',session.new), ('update',session.dirty), ('delete',session.deleted)):
            for obj in list(objects):
                if type(obj) not in MODELS.values() or (operation == 'update' and not session.is_modified(obj)):
                    continue
                expected[(obj.__tablename__, obj.id)] = (operation, row(obj))

    event.listen(db, 'after_flush', capture)
    try:
        edit = apply_edit(db, sale_id, data, db.get(User, raw_edit['user_id']), raw_edit['created_at'])
    finally:
        event.remove(db, 'after_flush', capture)
    # Buyruq jurnalida asl lokal qator IDlari qoladi; recovery aynan shu nusxani oladi.
    edit.command = raw_edit['command']
    expected_audits = [key for key in expected if key[0] == 'audit_logs']
    for key in inserted:
        model = MODELS[key[0]]
        values = final[key][1]
        if model is SaleEdit:
            central_id = edit.id
        elif model is Audit and len(expected_audits) == 1:
            central_id = expected_audits[0][1]
        elif model is MiniDiscountShare:
            item_id = mapped('sale_items', values['sale_item_id'])
            target = db.scalar(select(MiniDiscountShare).where(MiniDiscountShare.sale_item_id == item_id))
            if target is None:
                fail('Mini chegirma ulushi mos emas.')
            central_id = target.id
        else:
            fail('Tuzatishda kutilmagan yangi yozuv.')
        old = identity(db, device.id, key[0], key[1])
        if old and db.get(model, old.central_id) is None:
            db.delete(old)
            db.flush()
        remember(db, device.id, key[0], key[1], central_id)
    seen = set()
    for key, (operation, values) in final.items():
        model = MODELS[key[0]]
        central_id = mapped(key[0], key[1])
        expected_key = (key[0], central_id)
        if expected_key not in expected:
            fail('Tuzatishda ortiqcha o‘zgarish bor.')
        seen.add(expected_key)
        expected_op, expected_raw = expected[expected_key]
        if (operation == 'delete') != (expected_op == 'delete'):
            fail('Tuzatish amali hisobga mos emas.')
        values['id'] = central_id
        for name, target_model in LOCAL_REFS.items():
            if name in values:
                values[name] = mapped(target_model.__tablename__, values[name])
        actual = typed_row(model, row(db.get(model, central_id))) if operation != 'delete' else typed_row(model, expected_raw)
        if model is SaleEdit:
            actual['command'] = values['command']
        if model is Audit:
            detail = deepcopy(values['detail'])
            if detail.get('sale_id') != local_sale_id:
                fail('Tuzatish tarixi savdoga mos emas.')
            detail['sale_id'] = sale_id
            values['detail'] = detail
            # Audit vaqti qurilmada soniyaning bir qismiga farq qilishi mumkin.
            if abs((values['created_at'] - raw_edit['created_at']).total_seconds()) > 60:
                fail('Tuzatish tarixi vaqti mos emas.')
            actual['created_at'] = values['created_at']
            actual['actor'] = values['actor']
        if values != actual:
            fail('Tuzatish qatorlari qayta hisoblashga mos kelmadi: ' + key[0])
    if seen != set(expected):
        fail('Tuzatish paketida zarur yozuv yetishmaydi.')
    db.flush()
