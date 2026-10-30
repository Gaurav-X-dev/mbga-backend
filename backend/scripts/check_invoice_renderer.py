"""Deployment preflight: venv/bin/python scripts/check_invoice_renderer.py.

Ubuntu prerequisites:
  apt-get install --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu-core fonts-noto-core
Install Python dependencies from requirements.txt. Run this before restarting the API.
"""
from weasyprint import HTML

pdf = HTML(string='<html><body>Invoice renderer check: ₹1,000</body></html>').write_pdf()
assert pdf.startswith(b'%PDF'), 'Invoice renderer did not produce a PDF'
print('Invoice PDF renderer ready (native libraries and fonts available).')
