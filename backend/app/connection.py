"""EXE ulanishidagi xatolar: parol/token yoki server HTML'i foydalanuvchiga chiqmaydi."""
import httpx


class ConnectionProblem(ValueError):
    pass


class LegacyDeviceUnavailable(ConnectionProblem):
    code = 'legacy_device_unavailable'

    def __init__(self):
        super().__init__('Server eski qurilma ruxsatini qabul qilmadi. Baza yangilangan yoki qurilma bekor qilingan bo‘lishi mumkin. Eski bazani saqlab, markazga o‘z hisobingiz bilan kirishingiz mumkin.')


def connection_message(exc):
    if isinstance(exc, ConnectionProblem):
        return str(exc)
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        path = exc.request.url.path
        if 300 <= code < 400:
            return 'Server boshqa manzilga yo‘naltiryapti. Brauzerda ochilgan yakuniy HTTPS manzilini kiriting.'
        if code == 401:
            if path == '/api/auth/login':
                return 'Boshliq logini yoki paroli noto‘g‘ri. Markaziy serverdagi hisobni kiriting.'
            return 'Qurilma yoki seans tasdiqlanmadi. HTTPS manzili va serverdagi qurilma sozlamasini tekshiring.'
        if code == 403:
            return 'Ushbu amal uchun markaziy serverdagi boshliq hisobi kerak.'
        if code == 409 and path == '/api/sync/devices':
            return 'Bu filialga boshqa asosiy PC allaqachon biriktirilgan. Har filialga bitta PC: o‘z filialingizni tanlang. Ko‘chirish uchun eski PC zaxirasi kerak.'
        if code == 404:
            return 'Server manzili yoki filial topilmadi. Serverni va EXEni joriy versiyaga yangilang.'
        if code == 429:
            return 'Juda ko‘p kirish urinishi. Biroz kutib, to‘g‘ri login/parol bilan qayta urining.'
        return f'Server so‘rovni rad etdi (HTTP {code}). Ma’lumotlar o‘chirilmagan.'
    if isinstance(exc, httpx.TimeoutException):
        return 'Server vaqtida javob bermadi. Internet va server manzilini tekshirib qayta urining.'
    if isinstance(exc, httpx.TransportError):
        return 'Serverga ulanib bo‘lmadi. Manzil, internet va HTTPS sertifikatini tekshiring.'
    if isinstance(exc, OSError):
        return 'Lokal faylni yozib bo‘lmadi. Disk joyi va papka ruxsatini tekshiring.'
    return 'Sozlash yakunlanmadi. Server va EXE versiyalarini tekshiring; mavjud baza saqlangan.'
