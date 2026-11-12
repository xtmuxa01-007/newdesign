# Loyiha bilan ishlash

## Newdesign nusxasi — faqat lokal

2026-11-05 foydalanuvchi ushbu `Desktop/newdesign` nusxasini faqat lokal
dizayn va sun’iy ma’lumotlar sinovi uchun belgiladi. Bu nusxadan push,
release, CI/CD ishga tushirish yoki serverga deploy qilish taqiqlanadi.
Boshqa Marwa checkoutlari, ishchi server, AppData va haqiqiy bazalarga
tegilmang. Pastdagi server yo‘riqnomalari bu nusxani nashr qilishga ruxsat emas.
Lokal kirish nuqtasi: `scripts/run-local.py`; sinov bazasi:
`.runtime/local-web/demo.sqlite3`. Tartib: `docs/LOCAL_DESIGN_DEMO.md`.

Foydalanuvchi talabi: har bir o'zgarishda faqat amaldagi kod va joriy tayyor
paketlarni qoldiring. O'chirishdan oldin import, ishga tushirish, build, test,
CI/CD va yo'riqnomalardagi bog'lanishlarni tekshiring. Almashtirilgan kodni
`old`, `backup`, `v2` papkalarida qoldirmang; tarix Gitda saqlanadi.

- Asosiy rejim: https://tincrm.uz, web va Telegram Mini App markaziy PostgreSQL bazada.
  2026-11-05 foydalanuvchi EXE va eski lokal sinxronlashni vaqtincha to‘xtatdi.
  `CRM_DESKTOP_ENABLED=0` va `CRM_LEGACY_SYNC_ENABLED=0` holatini foydalanuvchi
  qayta yoqishni aniq so‘ramaguncha saqlang. EXE/AppData/lokal bazalarni o‘chirmang.
  Desktop kirish nuqtasi `desktop/shared-main.cjs`; kodi va eski backup/o‘tish
  vositalari keyin qayta ishlash uchun saqlanadi. Sinovda faqat disposable
  muhit ichida ikki flagni `1` qilib eski protokolni tekshirish mumkin.
- Eski lokal bazani zaxiralash, tiklash va markazga o'tkazish modullari hali
  ishlatiladi. Ularni faqat nomida `local` yoki `sync` borligi uchun o'chirmang.
- `.env`, SSH kalitlari, `.runtime/server-access`, foydalanuvchi AppData,
  bazalar, rasmlar, `backups` va serverdagi Docker volume'lar kod qoldig'i emas.
  Kodni tozalash ularni o'chirishga ruxsat bermaydi.
- Manba o'zgargach tegishli test/buildlarni o'tkazing. Yangi EXE tarqatilgach
  `scripts/clean-builds.ps1 -Apply` bilan eski lokal paketlar va build
  qoldiqlarini tozalang. Avval parametrsiz ko'rib chiqish mumkin.
- Serverga main orqali CI/CD bilan chiqaring. Sog'lom deploydan keyin eski
  release fayllari va ishlatilmayotgan build cache'ni tozalang; ishlayotgan
  konteyner, image yoki volume'ni o'chirmang. `docker system prune -a` va
  `docker volume prune` ishlatmang.
- GitHubda nashr qilingan versiyaning fayllarini almashtirmang. O'zgargan
  desktop uchun yangi versiya bering; Git tarixi va release arxivini saqlang.

Amaldagi tartib: README.md va docs/20_SERVERGA_JOYLASH_VA_ISHLATISH.txt.
