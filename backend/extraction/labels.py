"""Entity schema shared by the LayoutLMv3 extractor, the synthetic generator and the training script."""
HEADER_ENTITIES = ["VENDOR_NAME", "VENDOR_GSTIN", "BUYER_GSTIN", "INVOICE_NO", "INVOICE_DATE", "PO_NO",
                   "PLACE_OF_SUPPLY", "SUBTOTAL", "TOTAL_CGST", "TOTAL_SGST", "TOTAL_IGST", "ROUND_OFF",
                   "GRAND_TOTAL"]
ITEM_ENTITIES = ["ITEM_DESC", "ITEM_HSN", "ITEM_QTY", "ITEM_UNIT", "ITEM_PRICE", "ITEM_DISC", "ITEM_TAXABLE",
                 "ITEM_GSTRATE", "ITEM_CGST", "ITEM_SGST", "ITEM_IGST", "ITEM_TOTAL"]
ENTITIES = HEADER_ENTITIES + ITEM_ENTITIES
LABELS = ["O"] + [f"{p}-{e}" for e in ENTITIES for p in ("B", "I")]
LABEL2ID = {l: i for i, l in enumerate(LABELS)}
ID2LABEL = {i: l for l, i in LABEL2ID.items()}

# item entity -> LineItem attribute
ITEM_ATTR = {"ITEM_DESC": "description", "ITEM_HSN": "hsn_sac", "ITEM_QTY": "quantity", "ITEM_UNIT": "unit",
             "ITEM_PRICE": "unit_price", "ITEM_DISC": "discount", "ITEM_TAXABLE": "taxable_value",
             "ITEM_GSTRATE": "gst_rate", "ITEM_CGST": "cgst", "ITEM_SGST": "sgst", "ITEM_IGST": "igst",
             "ITEM_TOTAL": "line_total"}
HEADER_ATTR = {"VENDOR_NAME": "vendor_name", "VENDOR_GSTIN": "vendor_gstin", "BUYER_GSTIN": "buyer_gstin",
               "INVOICE_NO": "invoice_number", "INVOICE_DATE": "invoice_date", "PO_NO": "po_number",
               "PLACE_OF_SUPPLY": "place_of_supply", "SUBTOTAL": "subtotal", "TOTAL_CGST": "total_cgst",
               "TOTAL_SGST": "total_sgst", "TOTAL_IGST": "total_igst", "ROUND_OFF": "round_off",
               "GRAND_TOTAL": "grand_total"}
