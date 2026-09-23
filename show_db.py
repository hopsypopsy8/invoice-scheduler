from storage import get_all_invoices

rows = get_all_invoices()
print(f"{len(rows)} invoice(s) in database\n")
for row in rows:
    for key, value in row.items():
        print(f"{key:<18}{value}")
    print("-" * 40)