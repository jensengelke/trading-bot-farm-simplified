import requests
import xml.etree.ElementTree as ET
import time
import sys

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

print("Testing Flex Query SendRequest Rate Limit...")
for i in range(10):
    resp = requests.get(base_url, params=payload)
    print(f"[{i}] Status: {resp.status_code}")
    
    try:
        root = ET.fromstring(resp.content)
        status = root.find("Status").text if root.find("Status") is not None else "Unknown"
        err_code = root.find("ErrorCode").text if root.find("ErrorCode") is not None else "N/A"
        print(f"[{i}] XML Status: {status}, ErrorCode: {err_code}")
        
        if status == "Success":
            print(f"[{i}] Success! Reference Code: {root.find('ReferenceCode').text}")
            sys.exit(0)
    except Exception as e:
        print(f"[{i}] Parse error: {e}")
        
    print(f"[{i}] Waiting 10 seconds...")
    time.sleep(10)
