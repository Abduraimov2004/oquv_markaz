# 🚀 Serverga qo'yish — qadam-baqadam (oquv_markaz)

Bu qo'llanma **Ubuntu (Linux) VPS** uchun. Har bir buyruqni ketma-ket
serverda (SSH oynasida) bajaring. `SIZNING_*` joylarni o'zingiznikiga almashtiring.

> Bu loyiha **mustaqil** — boshqa loyihalardan alohida ishlaydi.

---

## 0. Kerakli narsalar (boshlashdan oldin)
- Ubuntu 22.04 yoki 24.04 **VPS** (IP manzil + root parol — hostingdan keladi).
- Loyiha **GitHub**da (private repo) — `git clone` uchun.
- **Supabase** loyihangiz tayyor va **barcha SQL migratsiyalar** (schema.sql ... schema_v16.sql) brauzerda RUN qilingan.
- Telegram **BOT_TOKEN** (@BotFather), Supabase **service_role key**, va bitta **SECRET_KEY** (uzun tasodifiy matn).

---

## 1. Serverga ulanish (SSH)
Windows'da **PowerShell** oching:
```bash
ssh root@SIZNING_IP
```
Parolni kiriting (host bergan). Birinchi marta "yes" deb tasdiqlang.

---

## 2. Kerakli dasturlarni o'rnatish
```bash
apt update && apt upgrade -y
apt install -y python3 python3-venv python3-pip git nginx
```

---

## 3. Kodni serverga olish (GitHub'dan)
```bash
cd /root
git clone SIZNING_GIT_URL oquv_markaz
cd oquv_markaz
```
> `SIZNING_GIT_URL` — GitHub repo manzili, masalan `https://github.com/USERNAME/oquv_markaz.git`
> Private repo bo'lsa, GitHub login/token so'raydi (yoki "Deploy key" sozlang).

---

## 4. Python muhiti + kutubxonalar
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 5. Maxfiy sozlamalar (.env)
```bash
cp .env.example .env
nano .env
```
Ochilgan oynada qiymatlarni to'ldiring:
```
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJ...        (service_role key)
SECRET_KEY=uzun-tasodifiy-matn
BOT_TOKEN=123456789:AA...
```
Saqlash: **Ctrl+O → Enter**, chiqish: **Ctrl+X**.

---

## 6. Sinab ko'rish (qo'lda)
```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Boshqa SSH oynada `curl http://127.0.0.1:8000` qilsangiz HTML qaytsa — ishlayapti.
**Ctrl+C** bilan to'xtating (keyin systemd doimiy ishlatadi).

---

## 7. Doimiy ishga tushirish (systemd) — web + bot + eslatma
Tayyor fayllarni nusxalaymiz:
```bash
cp /root/oquv_markaz/deploy/oquv-web.service       /etc/systemd/system/
cp /root/oquv_markaz/deploy/oquv-bot.service       /etc/systemd/system/
cp /root/oquv_markaz/deploy/oquv-reminders.service /etc/systemd/system/
cp /root/oquv_markaz/deploy/oquv-reminders.timer   /etc/systemd/system/

systemctl daemon-reload
systemctl enable --now oquv-web
systemctl enable --now oquv-bot
systemctl enable --now oquv-reminders.timer
```
Tekshirish:
```bash
systemctl status oquv-web --no-pager
systemctl status oquv-bot --no-pager
```
Yashil "active (running)" bo'lsa — web va bot doimiy ishlamoqda (server o'chib-yonsa ham o'zi qayta ishga tushadi).

---

## 8. Nginx (tashqaridan ochish uchun)
```bash
cp /root/oquv_markaz/deploy/nginx-oquv.conf /etc/nginx/sites-available/oquv
nano /etc/nginx/sites-available/oquv
```
`server_name SIZNING_DOMEN;` qatorini domeningizga o'zgartiring.
**Domen yo'q bo'lsa** — `server_name _;` qoldiring (IP orqali ochiladi).

Faollashtiramiz:
```bash
ln -s /etc/nginx/sites-available/oquv /etc/nginx/sites-enabled/oquv
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx
```

### Firewall (agar yoqilgan bo'lsa)
```bash
ufw allow 22
ufw allow 80
ufw allow 443
ufw --force enable
```

Endi brauzerda **http://SIZNING_IP** (yoki domeningiz) ochilishi kerak. ✅

---

## 9. Domen + HTTPS (ixtiyoriy, lekin tavsiya)
Avval domeningizning **A-record**ini serveringiz IP'siga yo'naltiring (domen panelida).
Keyin bepul SSL:
```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d SIZNING_DOMEN
```
Savollarga javob bering — `https://SIZNING_DOMEN` ishlaydi (avtomatik yangilanadi).

---

## ✅ Tayyor!
- Web panel: `http://SIZNING_IP` yoki `https://SIZNING_DOMEN`
- Telegram bot: doimiy ishlamoqda
- Kunlik eslatmalar: har kuni 09:00 da avtomatik

---

## 🔄 Keyinchalik yangilash (kod o'zgartirsangiz)
Kompyuterda: GitHub Desktop'da **Commit + Push**.
Keyin serverda:
```bash
cd /root/oquv_markaz
git pull
.venv/bin/pip install -r requirements.txt   # yangi kutubxona bo'lsa
systemctl restart oquv-web oquv-bot
```
> `.env` va yuklangan rasmlar saqlanib qoladi — `git pull` ularga tegmaydi.

---

## 🆘 Muammo bo'lsa — loglarni ko'rish
```bash
journalctl -u oquv-web -n 50 --no-pager     # web xatolari
journalctl -u oquv-bot -n 50 --no-pager     # bot xatolari
```
