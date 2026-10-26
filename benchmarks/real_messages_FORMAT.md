# Format: anonymized real messages with the colleague's actual entry

A larger test set made of real business messages (with the company's consent), anonymized. The "correct answer" is not what a model should say. It is **what the colleague actually entered into the POS**, or that they did not enter anything and asked back.

**Real data never goes into this repository.** Keep it outside the repo, in a folder for consented, private data. Only `real_messages.example.jsonl` here is synthetic.

## File

One JSON object per line (JSONL), UTF-8. See `real_messages.example.jsonl`.

| Field | Required | Content |
|---|---|---|
| `id` | yes | `r0001`, `r0002`, … with no meaning (not a date, phone or name) |
| `source_kind` | yes | `viber`, `sms`, `email`, `paper_photo_transcript`, `pdf_text` |
| `received_month` | yes | `YYYY-MM` only. An exact day or time can identify a person. |
| `text` | yes | The message exactly as received, after anonymization. Typos, abbreviations, `0,9O` and decimal commas **stay**: they are the value of the sample. |
| `expected.decision` | yes | `ENTERED` (written to the POS), `ASKED_BACK` (the colleague had to ask, which is the expected quarantine), `NOT_ENTERED` (ignored, e.g. not a price change) |
| `expected.lines[]` | when `ENTERED` | One object per POS row the colleague changed: `sku`, `name` (as in the POS), `qty` (or `null`), `unit_price` (decimal point, as a string), `currency` (ISO: `BAM`, `EUR`, `USD`), `price_basis` (`with_vat` / `before_tax`), `action` (`INSERT`, `UPDATE_PRICE`) |
| `expected.note` | no | Why: "no price, waited for the invoice", "line 3 unclear". Anonymized like `text`. |
| `anonymization_checked_by` | yes | Initials of the person who checked the record by hand |
| `synthetic` | no | `true` only for invented examples |

**Where the truth comes from:** the POS change log or price history for that day, matched to the message by the person preparing the set. If the colleague entered something wrong, record the value that was **eventually correct** and write the correction in `note`. The set measures the model against the correct outcome, not against the colleague's mistakes.

## Anonymization

| Replace | With | Example |
|---|---|---|
| Person names (including inflected forms) | `[IME1]`, `[IME2]` … consistently within one record | "pozdrav Ahmete" → "pozdrav [IME1]" |
| Phone numbers | `[TELEFON]` | |
| Addresses, postal code with city | `[ADRESA]` | |
| Store, supplier and company names | `[RADNJA1]`, `[FIRMA1]` | |
| E-mail, JIB/JMBG, IBAN, invoice numbers | `[EMAIL]`, `[BROJ]` | |

Items, quantities, prices, units and the structure of the message **stay**.

## Check before use

```powershell
.\.venv\Scripts\python.exe benchmarks\check_anonymized.py D:\private\messages.jsonl --blocklist D:\private\names.txt
```

| Part | What it does |
|---|---|
| Built-in checks | Looks for phone numbers, e-mail, URLs, JIB/JMBG (12–13 digits), IBAN, BHS and English addresses (`ul.`, `bb`, `71000 Sarajevo`, `Street`), legal forms (`d.o.o.`, `obrt`, `szr`) and shop words followed by a name (`prodavnica X`, `market X`) |
| `--blocklist` | A private file with the real names of people, stores and suppliers from the original data, one per line. Inflected forms are matched too (Ahmet → Ahmeta, Ahmetom). |
| Not flagged | Prices, quantities, 5-digit SKUs and dates |
| Output | Exit code 0 = clean. Exit code 1 = every finding printed **masked** (`06*******67`), so the output can be shared without revealing the data. |

A pattern cannot recognize every name. The final check is a person reading every record, and that person's initials go in `anonymization_checked_by`.
