"""Serve the local demo on loopback; remote integrations are blocked."""
from local_environment import ROOT, configure_local

configure_local()

from app.main import app
from fastapi.staticfiles import StaticFiles
import uvicorn


@app.middleware('http')
async def local_only_headers(request, call_next):
    response = await call_next(request)
    response.headers['X-Local-Only'] = '1'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    return response


app.mount('/', StaticFiles(directory=ROOT / 'frontend' / 'dist', html=True), name='local-web')
if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=18792, log_level='info')

