# Njuskalo Monitor - Mrvica Bot

Zadar-fokusirani monitor za njuskalo.hr.

Prati:
- Zemljišta Zadar, Okolica, Galovac
- Toyota Yaris Hybrid + Corolla
- Mazda CX-30
- Stanovi Zadar kvartovi
- Kuće Zadar okolica

Šalje obavijesti na **dva Telegram chata** (glavni + extra).

## Pokretanje
GitHub Actions (public repo):
- Cron: `35 * * * *` (svaki sat u :35)
- Ručni trigger: workflow_dispatch

## Secrets
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TELEGRAM_EXTRA_CHATS` (npr. `199701564,1327890117`)

## Baza
`njuskalo_mrvica.db` — vidjeni oglasi (commit-a se automatski natrag).

## Napomena
Ovo je lagana verzija glavnog bota, optimizirana za Zadar područje.
