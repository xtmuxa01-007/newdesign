# TIN CRM — Marwa Company

> **Ushbu `newdesign` nusxasi faqat lokal dizayn sinovi uchun.** Uni push,
> release yoki deploy qilmang va boshqa Marwa loyihalari bilan aralashtirmang.
> Lokal manzil: **http://127.0.0.1:18792**. Besh filial va uch oylik sun’iy
> savdo bazasi uchun [lokal sinov yo‘riqnomasi](docs/LOCAL_DESIGN_DEMO.md).
> Quyidagi ishlab turgan tizim haqidagi ma’lumotlar asl loyiha hujjatlaridir.

Amaldagi tizim: **https://tincrm.uz**. Web va Telegram Mini App markaziy
PostgreSQL bazada ishlaydi. Bir filialga bir nechta kompyuterdan kirish mumkin.
Savdo va tahrirlash uchun internet kerak. Xodimlar o‘z loginlari bilan kiradi.

**2026-11-05: Windows EXE va eski lokal sinxronlash vaqtincha to‘xtatilgan.**
Server EXE API so‘rovlari, eski qurilma sinxronlashlari va yangilash
yuklamalarini rad etadi. Eski qurilma yozuvi web tahririni bloklamaydi.
EXE fayllari, AppData, lokal bazalar, navbatlar va serverdagi biznes yozuvlari
saqlanadi. Foydalanuvchi aniq so‘ramaguncha qayta yoqilmaydi.

Lokal tayyor Windows paketi: **0.5.3**. `desktop/release` ichida shu versiyaning
installer, SHA256, yangilash manifesti va server manbalari ZIPi saqlanadi.
Eski paketlar muvaffaqiyatli tarqatishdan keyin tozalanadi. Serverda tarqatilayotgan
versiya `https://tincrm.uz/api/desktop/updates/latest.yml` manifestida ko‘rsatiladi.

- [Web/EXE, yangilash va eski PCdan o‘tish](docs/30_UMUMIY_WEB_VA_EXE.txt)
- [EXE va eski sinxronlashning vaqtinchalik to‘xtatilishi](docs/40_EXE_VA_LOKAL_SYNC_TOXTATILGAN.txt)
- [Telegram Mini App](docs/37_TELEGRAM_MINI_APP.txt)
- [Telegram kunlik savdo va ombor hisoboti](docs/38_TELEGRAM_KUNLIK_HISOBOT.txt)
- [Boshqa pullarni topshirish va boshliq bildirishnomasi](docs/39_BOSHQA_PULLAR.txt)
- [Server va CI/CD](docs/20_SERVERGA_JOYLASH_VA_ISHLATISH.txt)
- [Tozalash tartibi](docs/21_TOZA_VERSIYA.txt)
- [Programmist va filial arxivi](docs/31_FILIAL_ARXIVI_VA_PROGRAMMIST.txt)
- [Mahsulot arxivi va alohida baza reset amali](docs/32_MAHSULOT_ARXIVI_VA_BAZANI_TOZALASH.txt)
- [SKU va ombor qoldig‘ini tahrirlash](docs/33_SKU_VA_QOLDIQ_TAHRIRI.txt)
- [Mahsulot tahlili va joriy sotuv narxini tahrirlash](docs/35_MAHSULOT_TAHLILI_VA_NARX_TAHRIRI.txt)
- [Ehson limiti va xato amalni bekor qilish](docs/34_EHSON_LIMITI_VA_AMALNI_BEKOR_QILISH.txt)
- [Savdo tarixi, Excel va savdolar analizi](docs/06_HISOBOT_TARIX_JSON.txt)
- [Narx/savdo o‘zgarishlari va boshliq bildirishnomalari](docs/36_OZGARISHLAR_VA_BILDIRISHNOMALAR.txt)
- [Loginni almashtirish va hisob huquqlari](docs/02_ROLLAR_VA_KIRISH.txt)
- [Savdo qarzi va avval berilgan qarzni mahsulotsiz kiritish](docs/15_WEB_QARZLAR.txt)
- [O‘zgarishlar tarixi](docs/12_DOIMIY_ISHLAR_JURNALI.txt)

Programmist hisobi (dastlabki login: `abduqodir`): filial/mahsulotni tarix bilan arxivlash va tiklash,
SKU tahriri hamda qoldiq tuzatishini bekor qilish huquqi shu hisobga bog‘langan.
Admin o‘z filialida, boshliq tanlangan filialda kg qoldig‘ini sabab bilan tuzatadi.
Loginni almashtirish hisobning huquqlari va tarixini saqlaydi. Parol manba
kodida saqlanmaydi.

«Savdolar va tarix»da filial va sana oralig‘i bo‘yicha barcha savdolarni
Excel yoki JSONga yuklash mumkin. «Savdolar analizi» boshliq/admin uchun:
oy/davr va filial tanlovi, kunlik/oylik grafiklar, mahsulot qiymati, tushum,
qarz, ehson va xarajatlar alohida ko‘rsatiladi. Analiz Excelga grafik va
jadvallar bilan yuklanadi. Jami tushum savdoda olingan pul va tanlangan
davrda yig‘ilgan qarz to‘lovlaridan iborat; bu kassa qoldig‘i yoki foyda emas.

«Ombor → Tahlil» mahsulotning hozirgi qoldig‘i va tanlangan davrdagi savdo,
kirim hamda narx tarixini ko‘rsatadi. «Narxni o‘zgartirish» orqali admin o‘z
filialida, boshliq tanlangan faol filialda sabab bilan joriy sotuv narxini
belgilaydi. Eski savdo va kirim narxlari, kilogramm qoldig‘i va chegirma saqlanadi.
Shu oynadagi «Kilogramni tuzatish» reviziyadan keyingi haqiqiy jami qoldiqni
belgilaydi. Oldingi/yangi kg, farq, sabab va xodim tarixda saqlanadi; boshliqlarga
ilova ichida bildirishnoma boradi. Savdo, kirim, kassa va qarz yozuvlari qayta yozilmaydi.

«Savdolar va tarix → O‘zgarishlar»da narx tahrirlari va bekor qilingan
savdolarni filial, sana va amal turi bo‘yicha ko‘rish mumkin. Boshliq uchun
barcha filiallardan dastur ichidagi bildirishnomalar bor. O‘qilganlik har
bir boshliq hisobiga alohida saqlanadi; asl o‘zgarish tarixi qoladi.

O‘z loginini «Sozlamalar → Login va parol»da, boshliq esa xodim loginini
«Jamoa va filiallar → Login va parol»da almashtiradi. Yangi parolni bo‘sh
qoldirish avvalgi parolni saqlaydi; login/parol o‘zgarsa qayta kirish kerak.

Avval berilgan qarzni «Qarzlar → Oldingi qarzni kiritish»da mahsulotsiz
yozish mumkin: filial, qarzdor va summa tanlanadi. Admin/boshliq kiritadi,
kassir ham o‘z filialida to‘lov qabul qiladi. Qarzning o‘zi kassa/ombor yoki
mahsulot savdosini o‘zgartirmaydi; to‘langanda naqd/karta kassaga qo‘shiladi.
Qarzga muddatidan oldin yoki keyin qisman to‘lov qabul qilish, qolgan qarzga
yangi sana belgilash mumkin. Har bir to‘lov, muddat va ma’lumot tuzatishi
tarixda saqlanadi. Xato qarz yoki to‘lov sabab bilan bekor qilinadi.

## Ishlab chiqish

Backend: `backend/app`; frontend: `frontend/src`; EXE: `desktop/shared-main.cjs`.
Eski lokal bazadan o‘tish uchun backup/sync modullari kerak va saqlanadi.
Python kutubxonalari requirements fayllari, Node kutubxonalari pnpm lock bilan
mahkamlangan. Alohida venv talab qilinmaydi.

```powershell
python -m pip install --target .build-deps -r backend/requirements-desktop.txt
$env:PYTHONPATH = "$PWD\backend;$PWD\.build-deps"
python -m unittest discover -s backend/tests -v
node --test desktop/shared-main.test.cjs desktop/updater.test.cjs desktop/updater-download.test.cjs
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend test
pnpm --dir frontend build
pnpm --dir desktop install --frozen-lockfile
python scripts/build_desktop.py
pnpm --dir desktop dist
python scripts/build_update_manifest.py
python scripts/build_server_package.py
```

PostgreSQL testlari CI ichidagi alohida marva-ci bazada bajariladi. Lokal Docker
sinovi uchun `.env.example` asosida `.env` yarating va `scripts/start.ps1`ni
ishlating. Bu ishlab chiqish muhiti; ishchi savdo markazi tincrm.uz.

`main`ga push testlardan keyin serverni yangilaydi. Windows installer alohida
GitHub release va TIN desktop distribution orqali tarqatiladi. Nashr qilingan
versiya fayli almashtirilmaydi: desktop o‘zgarsa versiya oshiriladi.

Har ishda [AGENTS.md](AGENTS.md)dagi tozalash qoidalariga amal qiling.
