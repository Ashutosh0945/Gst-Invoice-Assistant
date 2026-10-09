# Real-invoice collection protocol (target: 300–500 invoices, 50+ different vendors)

The experiments showed **layout/format variety matters more than volume** (E2, E4, E6/E7), so aim for many vendors,
not many invoices from the same vendor (max ~10 per vendor).

1. **Approval**: get a permission letter from your guide/HOD before contacting anyone.
2. **Sources** (with signed CONSENT_FORM.md): team families' purchase invoices (electronics, e-commerce B2B invoices),
   local shops and wholesalers, CA firms (ask for already-redacted copies), college accounts / canteen vendors.
3. **Capture**: for each paper invoice, take 2 phone photos (one good, one casual: angled/shadowed) using the app's camera
   flow; keep PDFs as-is. Name files `vendor-code_invoice-seq_photo-n.jpg` — never the real vendor name.
4. **Anonymise first**: run OCR/labelling only on anonymised copies (`python -m research.data_collection.anonymize`).
5. **Label** in Label Studio with `label_studio_config.xml`; pre-fill with the app's extractor to save time; two people
   label 10% of invoices independently to measure agreement.
6. **Convert** with `labelstudio_to_kie.py`; **split by vendor** (test vendors never appear in training).
7. **Experiments to run with real data** (scripts already accept the KIE JSON format):
   - synthetic-only model tested on real invoices (sim-to-real gap),
   - fine-tune with 25 / 50 / 100 / 200 real invoices (data-efficiency curve),
   - photos with vs without camera optimisation.
