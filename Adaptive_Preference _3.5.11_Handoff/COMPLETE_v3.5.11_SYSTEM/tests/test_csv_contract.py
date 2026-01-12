import re, io, os

def test_csv_contract_file_present():
    assert os.path.exists('contracts/CSV_EXPORT_CONTRACT.md')

