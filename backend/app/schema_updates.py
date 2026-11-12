"""Small, transactional compatibility updates; never replace business records."""
import re

from sqlalchemy import inspect, text


_OLD_KINDS = frozenset(('sale', 'receipt', 'supplier_payment', 'donation_payment',
                        'expense', 'debt_payment', 'stock_adjustment'))
_NEW_KINDS = _OLD_KINDS | {'other_payment'}
_LITERAL = re.compile(r"'((?:''|[^'])*)'")
_CHECK = "kind IN ('sale','receipt','supplier_payment','donation_payment','other_payment','expense','debt_payment','stock_adjustment')"


def _kind_values(sql):
    """Recognize only the known single-column enum, including pg_get_constraintdef.

    Removing a broader expression such as ``kind IN (...) OR ...`` would change
    another business rule, so unfamiliar syntax is deliberately refused.
    """
    if not isinstance(sql, str):
        raise RuntimeError('Bekor qilish turlari cheklovini tekshirib bo‘lmadi.')
    values = [value.replace("''", "'") for value in _LITERAL.findall(sql)]
    skeleton = _LITERAL.sub('VALUE', sql)
    skeleton = re.sub(r'::\s*(?:character\s+varying|varchar|text)(?:\s*\[\s*\])?', '', skeleton, flags=re.I)
    skeleton = re.sub(r'"kind"', 'kind', skeleton, flags=re.I)
    skeleton = re.sub(r'[\s()\[\]]', '', skeleton).upper()
    expected = ','.join(['VALUE'] * len(values))
    if (not values or len(set(values)) != len(values) or
            frozenset(values) not in (_OLD_KINDS, _NEW_KINDS) or
            skeleton not in ('KINDIN' + expected, 'KIND=ANYARRAY' + expected)):
        raise RuntimeError('Bekor qilish turlari cheklovi kutilgan sxemaga mos emas. Avval tekshiring.')
    return frozenset(values)


def _kind_checks(connection):
    result = []
    for constraint in inspect(connection).get_check_constraints('operation_cancellations'):
        sql = constraint.get('sqltext')
        if not isinstance(sql, str) or not re.search(r'\bkind\b', sql, flags=re.I):
            continue
        name = constraint.get('name')
        if not isinstance(name, str) or not name:
            raise RuntimeError('Bekor qilish turlari cheklovining nomi topilmadi.')
        result.append((name, _kind_values(sql)))
    if not result:
        raise RuntimeError('Bekor qilish turlari cheklovi topilmadi. Avval sxemani tekshiring.')
    return result


def ensure_other_payment_kind(engine):
    """Expand only the existing PostgreSQL kind check, atomically and once.

    create_all does not alter an existing check. SQLite offline databases do
    not write OtherPayment; fresh SQLite fixtures already use current metadata.
    No SQLite table rebuild, data copying, truncation or account change occurs.
    """
    if engine.dialect.name != 'postgresql':
        return False
    with engine.begin() as connection:
        checks = _kind_checks(connection)
        if all(values == _NEW_KINDS for _, values in checks):
            return False
        # Parallel API startups may have inspected the old check simultaneously.
        connection.execute(text('LOCK TABLE operation_cancellations IN ACCESS EXCLUSIVE MODE'))
        checks = _kind_checks(connection)
        changed = False
        quote = connection.dialect.identifier_preparer.quote_identifier
        for name, values in checks:
            if values == _NEW_KINDS:
                continue
            connection.execute(text('ALTER TABLE operation_cancellations DROP CONSTRAINT ' + quote(name)))
            connection.execute(text('ALTER TABLE operation_cancellations ADD CONSTRAINT ' + quote(name) + ' CHECK (' + _CHECK + ')'))
            changed = True
        return changed
