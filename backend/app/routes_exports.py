"""Excel exports use the same server-side branch and date permissions as reports."""
from datetime import date
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from .common import audit, row
from .db import get_db
from .excel_reports import XLSX_TYPE, sales_workbook, analytics_workbook
from .models import Branch, Sale, User
from .routes_finance import period
from .routes_sales import sale_data
from .security import manager, branch_scope

router = APIRouter(prefix='/api')


def response(data, filename):
    return Response(data, media_type=XLSX_TYPE,
                    headers={'Content-Disposition': f'attachment; filename="{filename}"'})


def sales_snapshot(db, branch_id, start, end):
    query = select(Sale, User.name).join(User, User.id == Sale.user_id).where(*period(start, end)).order_by(Sale.id)
    branch_query = select(Branch).order_by(Branch.id)
    if branch_id is not None:
        query = query.where(Sale.branch_id == branch_id)
        branch_query = branch_query.where(Branch.id == branch_id)
    entries = [dict(sale_data(db, sale), cashier=cashier) for sale, cashier in db.execute(query)]
    branches = [row(branch) for branch in db.scalars(branch_query)]
    return sales_workbook(entries, branches, start, end, branch_id), len(entries)


@router.get('/sales/export.xlsx')
def export_sales_xlsx(branch_id: int | None = None, start: date | None = None, end: date | None = None,
                      user=Depends(manager), db: Session = Depends(get_db)):
    branch_id = branch_scope(db, user, branch_id)
    # Validate before opening an additional reporting connection.
    period(start, end)
    if db.get_bind().dialect.name == 'postgresql':
        # Authentication already read from the original transaction. A fresh
        # read-only snapshot keeps header, items and debt from the same version
        # while another PC edits/cancels the sale. SQLite's existing transaction
        # is already consistent and must not open a second BEGIN IMMEDIATE.
        with db.get_bind().connect().execution_options(isolation_level='REPEATABLE READ') as connection:
            with Session(bind=connection) as snapshot:
                snapshot.execute(text('SET TRANSACTION READ ONLY'))
                content, count = sales_snapshot(snapshot, branch_id, start, end)
    else:
        content, count = sales_snapshot(db, branch_id, start, end)
    audit(db, user, 'Savdolar Excel yuklandi', branch_id, count=count, start=start, end=end)
    db.commit()
    return response(content, f'marwa-savdolar-{branch_id or "barcha"}-{start or "boshidan"}-{end or "hozirgacha"}.xlsx')


@router.get('/sales/analytics/export.xlsx')
def export_analytics_xlsx(branch_id: int | None = None, start: date | None = None, end: date | None = None,
                          user=Depends(manager), db: Session = Depends(get_db)):
    from .routes_analytics import analysis_dates, build_sales_analytics
    branch_id = branch_scope(db, user, branch_id)
    start, end = analysis_dates(start, end)
    data = build_sales_analytics(db, branch_id, start, end)
    content = analytics_workbook(data)
    scope = data['filter']
    audit(db, user, 'Savdolar analizi Excel yuklandi', scope['branch_id'],
          count=data['summary']['sales_count'], start=scope['start'], end=scope['end'])
    db.commit()
    return response(content, f'marwa-analiz-{scope["branch_id"] or "barcha"}-{scope["start"]}-{scope["end"]}.xlsx')
