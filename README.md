# Afina

Windows desktop application for Yandex Direct reports, Yandex Metrica visitors and a read-only ad catalog. Public source snapshot v2.2.

## Run

Install Python 3.12+ with tkinter, then launch `START_AFINA.cmd` or `python desktop.py`.
For an offline demonstration use `python desktop.py --demo`.

Register your own Yandex OAuth application. In PowerShell, set the public application ID before launch:

```powershell
$env:AFINA_CLIENT_ID = "YOUR_32_CHARACTER_CLIENT_ID"
python desktop.py
```

The all-zero default is a placeholder, not a usable account. Counter lists start empty; add your own IDs in the Metrica tab. OAuth codes must be entered only in the local application. Tokens are stored in Windows Credential Manager, never in this repository.

This version does not change live ads. Banner replacements are local draft plans only. Account permissions are not independently verified as read-only. Read the accompanying Russian README files for feature boundaries.

## Tests

```sh
python -m unittest discover -q
```

Tests use synthetic fixtures. Real account connectivity and full Windows visual QA are separate from offline testing.

## Privacy

Do not commit tokens, passwords, authorization codes, client secrets, exports or local settings. This public snapshot excludes personal account IDs, prefilled counter IDs and company-specific report data. Demo figures are synthetic.
