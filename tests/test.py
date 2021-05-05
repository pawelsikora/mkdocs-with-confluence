import requests
import mimetypes

# -----------------------------------------------------------------------------
# Globals

BASE_URL = "<YOUR_DOMAIN>/rest/api/content"
SPACE_NAME = "<YOUR_SPACE_NAME>"
USERNAME = "<YOUR_USERNAME>"
PASSWORD = "<YOUR_PASSWORD>"


def upload_attachment(page_id, filepath):
    url = BASE_URL + "/" + page_id + "/child/attachment/"
    headers = {"X-Atlassian-Token": "no-check"}  # no content-type here!
    print(f"URL: {url}")
    filename = filepath

    # determine content-type
    content_type, encoding = mimetypes.guess_type(filename)
    if content_type is None:
        content_type = "multipart/form-data"

    # provide content-type explicitly
    files = {"file": (filename, open(filename, "rb"), content_type)}
    print(f"FILES: {files}")

    auth = (USERNAME, PASSWORD)
    r = requests.post(url, headers=headers, files=files, auth=auth)
    r.raise_for_status()


def find_parent_name_of_page(name):
    idp = find_page_id(name)
    url = BASE_URL + "/" + idp + "?expand=ancestors"
    print(f"URL: {url}")

    auth = (USERNAME, PASSWORD)
    r = requests.get(url, auth=auth)
    r.raise_for_status()
    response_json = r.json()
    if response_json:
        print(f"ID: {response_json['ancestors'][0]['title']}")
        return response_json
    else:
        print("PAGE DOES NOT EXIST")
        return None


def find_page_id(name):
    name_confl = name.replace(" ", "+")
    url = BASE_URL + "?title=" + name_confl + "&spaceKey=" + SPACE_NAME + "&expand=history"
    print(f"URL: {url}")

    auth = (USERNAME, PASSWORD)
    r = requests.get(url, auth=auth)
    r.raise_for_status()
    response_json = r.json()
    if response_json["results"]:
        print(f"ID: {response_json['results']}")
        return response_json["results"]
    else:
        print("PAGE DOES NOT EXIST")
        return None


def add_page(page_name, parent_page_id):
    url = BASE_URL + "/"
    print(f"URL: {url}")
    headers = {"Content-Type": "application/json"}
    auth = (USERNAME, PASSWORD)
    data = {
        "type": "page",
        "title": page_name,
        "space": {"key": SPACE_NAME},
        "ancestors": [{"id": parent_page_id}],
        "body": {"storage": {"value": "<p>This is a new page</p>", "representation": "storage"}},
    }

    r = requests.post(url, json=data, headers=headers, auth=auth)
    r.raise_for_status()
    print(r.json())


def update_page(page_name):
    page_id = find_page_id(page_name)
    if page_id:
        page_version = find_page_version(page_name)
        page_version = page_version + 1
        print(f"PAGE ID: {page_id}, PAGE NAME: {page_name}")
        url = BASE_URL + "/" + page_id
        print(f"URL: {url}")
        headers = {"Content-Type": "application/json"}
        auth = (USERNAME, PASSWORD)
        data = {
            "type": "page",
            "space": {"key": SPACE_NAME},
            "body": {"storage": {"value": "<p>Let the dragons out!</p>", "representation": "storage"}},
            "version": {"number": page_version},
        }

        data["id"] = page_id
        data["title"] = page_name
        print(data)

        r = requests.put(url, json=data, headers=headers, auth=auth)
        r.raise_for_status()
        print(r.json())
    else:
        print("PAGE DOES NOT EXIST. CREATING WITH DEFAULT BODY")
        add_page(page_name)


def find_page_version(name):
    name_confl = name.replace(" ", "+")
    url = BASE_URL + "?title=" + name_confl + "&spaceKey=" + SPACE_NAME + "&expand=version"

    print(f"URL: {url}")

    auth = (USERNAME, PASSWORD)
    r = requests.get(url, auth=auth)
    r.raise_for_status()
    response_json = r.json()
    if response_json["results"]:
        print(f"VERSION: {response_json['results'][0]['version']['number']}")
        return response_json["results"][0]["version"]["number"]
    else:
        print("PAGE DOES NOT EXISTS")
        return None


# add_page()
# update_page("Test Page")
# find_page_version("Test Page")
# find_parent_name_of_page("Test Parent Page")
# find_page_id("Test Page")
# upload_attachment()
