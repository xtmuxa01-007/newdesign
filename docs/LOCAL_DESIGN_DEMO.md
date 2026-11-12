# Newdesign — faqat lokal dizayn va sinov

Bu checkout boshqa Marwa loyihalaridan alohida dizayn sinovi uchun ishlatiladi.
Uni push, release yoki deploy qilmang. Ishchi server, AppData, haqiqiy hisoblar
va boshqa lokal bazalar bu sinovga ulanmaydi.

Manzil: http://127.0.0.1:18792

Asosiy hisob: `abduqodir` / `LocalTin2026!`.
Filial hisoblari: `admin1`–`admin5`, `kassir1`–`kassir5`; parol shu sinov paroli.
Bu parol faqat sun’iy lokal baza uchun.

Sinov davri: **2026-08-06 — 2026-11-05**. Besh filial, yigirmata mahsulot,
ta’minotchilar, kundalik savdolar, qarzlar, qisman to‘lovlar, ehsonlar va
xarajatlar mavjud. Barcha yozuvlar sun’iy; haqiqiy ma’lumot import qilinmaydi.

## Ishga tushirish

Loyihaning mavjud `.build-deps` va `frontend/node_modules` kutubxonalari ishlatiladi:

```powershell
node frontend/node_modules/vite/bin/vite.js build frontend
python scripts/seed-local-demo.py
python scripts/run-local.py
```

`scripts/local_environment.py` bazani qat’iy ravishda
`.runtime/local-web/demo.sqlite3` bilan cheklaydi. `.env` o‘qilmaydi; meros
bo‘lgan CRM, Telegram va baza sozlamalari tozalanadi. EXE, eski sinxronlash
va Telegram ishchilari o‘chiq. Python audit hook tashqi DNS, tashqi ulanishlar
va loopbackdan tashqarida port ochishni rad etadi. Boshqa localhost xizmatlariga
ham chiqish bloklanadi. Brauzer CSP faqat shu lokal
origin bilan aloqa va mahalliy aktivlarga ruxsat beradi.

Seeder mavjud filial yoki savdolarni ko‘rsa ularni o‘zgartirmasdan chiqadi.
U baza reset, restore yoki tozalash amalini bajarmaydi. Oldingi
`development.sqlite3` fayli saqlanadi va yangi sinovda ishlatilmaydi.

Joriy sinov bazasining mustaqil nusxasi: `artifacts/tin-demo.sqlite3`.
Nusxa SQLite backup API bilan olingan; unda faol seanslar yo‘q.

## Logotip

Asl logotip rasmi `frontend/public/tin-logo.png`: 1254×1254 RGBA PNG.
U avvalgi SVG ichidan o‘zgartirilmasdan ajratib olingan. Ilova va favicon
shu yagona PNGdan foydalanadi.
