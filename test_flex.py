import requests
import xml.etree.ElementTree as ET

token = "418460991372630500000"
query_id = "1383385"
base_url = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest"

payload = {
    "t": token,
    "q": query_id,
    "v": 3,
    "fd": "20260201",
    "td": "20260228"
}

resp = requests.get(base_url, params=payload)
print(resp.status_code)
print(resp.text)
