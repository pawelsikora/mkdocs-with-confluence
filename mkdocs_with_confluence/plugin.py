import time
import os
import hashlib
import sys
import re
import tempfile
import shutil
import requests
import mimetypes
import mistune
import contextlib
from time import sleep
from mkdocs.config import config_options
from mkdocs.plugins import BasePlugin
from md2cf.confluence_renderer import ConfluenceRenderer
from os import environ
from pathlib import Path

TEMPLATE_BODY = "<p> TEMPLATE </p>"


@contextlib.contextmanager
def nostdout():
    save_stdout = sys.stdout
    sys.stdout = DummyFile()
    yield
    sys.stdout = save_stdout


class DummyFile(object):
    def write(self, x):
        pass

class MkdocsConfluenceRenderer(ConfluenceRenderer):
    def __init__(self, mkdocs_plugin=None, **kwargs):
        super().__init__(**kwargs)
        self.mkdocs_plugin = mkdocs_plugin
        
    def link(self, link, title, text):
        if self.mkdocs_plugin and '://' not in link and link.endswith('.md'):
            title = self._page_title_by_relative_file_path(link)
            if title:
                page_id = self.mkdocs_plugin.find_page_id(title)
                if page_id:
                    link = self.mkdocs_plugin.config['host_url'].replace(
                        '/rest/api/content',
                        f'/spaces/{self.mkdocs_plugin.config["space"]}/pages/{page_id}'
                    )

        return super().link(link, title, text)

    def _page_title_by_relative_file_path(self, path):
        my_path = self.mkdocs_plugin.current_page.file.src_uri
        their_path = os.path.normpath(os.path.join(os.path.dirname(my_path), path))
        for page in self.mkdocs_plugin.pages:
            if page.file.src_uri == their_path:
                return page.title

        return None
            

class MkdocsWithConfluence(BasePlugin):
    _id = 0
    config_scheme = (
        ("host_url", config_options.Type(str, default=None)),
        ("space", config_options.Type(str, default=None)),
        ("parent_page_name", config_options.Type(str, default=None)),
        ("username", config_options.Type(str, default=environ.get("JIRA_USERNAME", None))),
        ("password", config_options.Type(str, default=environ.get("JIRA_PASSWORD", None))),
        ("enabled_if_env", config_options.Type(str, default=None)),
        ("verbose", config_options.Type(bool, default=False)),
        ("debug", config_options.Type(bool, default=False)),
        ("dryrun", config_options.Type(bool, default=False)),
    )

    def __init__(self):
        self.enabled = True
        self.confluence_renderer = MkdocsConfluenceRenderer(
            mkdocs_plugin=self, use_xhtml=True, remove_text_newlines=True
        )
        self.confluence_mistune = mistune.Markdown(renderer=self.confluence_renderer)
        self.simple_log = False
        self.flen = 1
        self.session = requests.Session()
        self.page_attachments = {}
        self.current_page = None
        self.pages = None

    def on_nav(self, nav, config, files):
        self.pages = nav.pages
        MkdocsWithConfluence.tab_nav = []
        navigation_items = nav.__repr__()

        for n in navigation_items.split("\n"):
            leading_spaces = len(n) - len(n.lstrip(" "))
            spaces = leading_spaces * " "
            if "Page" in n:
                try:
                    self.page_title = self.__get_page_title(n)
                    if self.page_title is None:
                        raise AttributeError
                except AttributeError:
                    self.page_local_path = self.__get_page_url(n)
                    print(
                        f"WARN    - Page from path {self.page_local_path} has no"
                        f"          entity in the mkdocs.yml nav section. It will be uploaded"
                        f"          to the Confluence, but you may not see it on the web server!"
                    )
                    self.page_local_name = self.__get_page_name(n)
                    self.page_title = self.page_local_name

                p = spaces + self.page_title
                MkdocsWithConfluence.tab_nav.append(p)
            if "Section" in n:
                try:
                    self.section_title = self.__get_section_title(n)
                    if self.section_title is None:
                        raise AttributeError
                except AttributeError:
                    self.section_local_path = self.__get_page_url(n)
                    print(
                        f"WARN    - Section from path {self.section_local_path} has no"
                        f"          entity in the mkdocs.yml nav section. It will be uploaded"
                        f"          to the Confluence, but you may not see it on the web server!"
                    )
                    self.section_local_name = self.__get_section_title(n)
                    self.section_title = self.section_local_name
                s = spaces + self.section_title
                MkdocsWithConfluence.tab_nav.append(s)

    def on_files(self, files, config):
        pages = files.documentation_pages()
        try:
            self.flen = len(pages)
            print(f"Number of Files in directory tree: {self.flen}")
        except 0:
            print("ERR: You have no documentation pages" "in the directory tree, please add at least one!")

    def on_post_template(self, output_content, template_name, config):
        if self.config["verbose"] is False and self.config["debug"] is False:
            self.simple_log = True
            print("INFO    -  Mkdocs With Confluence: Start exporting markdown pages... (simple logging)")
        else:
            self.simple_log = False

    def on_config(self, config):
        if "enabled_if_env" in self.config:
            env_name = self.config["enabled_if_env"]
            if env_name:
                self.enabled = os.environ.get(env_name) == "1"
                if not self.enabled:
                    print(
                        "WARNING - Mkdocs With Confluence: Exporting MKDOCS pages to Confluence turned OFF: "
                        f"(set environment variable {env_name} to 1 to enable)"
                    )
                    return
                else:
                    print(
                        "INFO    -  Mkdocs With Confluence: Exporting MKDOCS pages to Confluence "
                        f"turned ON by var {env_name}==1!"
                    )
                    self.enabled = True
            else:
                print(
                    "WARNING -  Mkdocs With Confluence: Exporting MKDOCS pages to Confluence turned OFF: "
                    f"(set environment variable {env_name} to 1 to enable)"
                )
                return
        else:
            print("INFO    -  Mkdocs With Confluence: Exporting MKDOCS pages to Confluence turned ON by default!")
            self.enabled = True

        if self.config["dryrun"]:
            print("WARNING -  Mkdocs With Confluence - DRYRUN MODE turned ON")
            self.dryrun = True
        else:
            self.dryrun = False

    def on_page_markdown(self, markdown, page, config, files):
        MkdocsWithConfluence._id += 1
        self.session.auth = (self.config["username"], self.config["password"])
        self.current_page = page

        if self.enabled:
            if self.simple_log is True:
                print("INFO    - Mkdocs With Confluence: Page export progress: [", end="", flush=True)
                for i in range(MkdocsWithConfluence._id):
                    print("#", end="", flush=True)
                for j in range(self.flen - MkdocsWithConfluence._id):
                    print("-", end="", flush=True)
                print(f"] ({MkdocsWithConfluence._id} / {self.flen})", end="\r", flush=True)

            if self.config["debug"]:
                print(f"\nDEBUG    - Handling Page '{page.title}' (And Parent Nav Pages if necessary):\n")
            if not all(self.config_scheme):
                print("DEBUG    - ERR: YOU HAVE EMPTY VALUES IN YOUR CONFIG. ABORTING")
                return markdown

            try:
                if self.config["debug"]:
                    print("DEBUG    - Get section first parent title...: ")
                try:

                    parent = self.__get_section_title(page.ancestors[0].__repr__())
                except IndexError as e:
                    if self.config["debug"]:
                        print(
                            f"DEBUG    - WRN({e}): No first parent! Assuming "
                            f"DEBUG    - {self.config['parent_page_name']}..."
                        )
                    parent = None
                if self.config["debug"]:
                    print(f"DEBUG    - {parent}")
                if not parent:
                    parent = self.config["parent_page_name"]

                if self.config["parent_page_name"] is not None:
                    main_parent = self.config["parent_page_name"]
                else:
                    main_parent = self.config["space"]

                if self.config["debug"]:
                    print("DEBUG    - Get section second parent title...: ")
                try:
                    parent1 = self.__get_section_title(page.ancestors[1].__repr__())
                except IndexError as e:
                    if self.config["debug"]:
                        print(
                            f"DEBUG    - ERR({e}) No second parent! Assuming "
                            f"second parent is main parent: {main_parent}..."
                        )
                    parent1 = None
                if self.config["debug"]:
                    print(f"{parent}")

                if not parent1:
                    parent1 = main_parent
                    if self.config["debug"]:
                        print(
                            f"DEBUG    - ONLY ONE PARENT FOUND. ASSUMING AS A "
                            f"FIRST NODE after main parent config {main_parent}"
                        )

                if self.config["debug"]:
                    print(f"DEBUG    - PARENT0: {parent}, PARENT1: {parent1}, MAIN PARENT: {main_parent}")

                tf = tempfile.NamedTemporaryFile(delete=False)
                f = open(tf.name, "w")

                attachments = []
                try:
                    for match in re.finditer(r'img src="file://(.*)" s', markdown):
                        if self.config["debug"]:
                            print(f"DEBUG    - FOUND IMAGE: {match.group(1)}")
                        attachments.append(match.group(1))
                    for match in re.finditer(r"!\[[\w\. -]*\]\((?!http|file)([^\s,]*).*\)", markdown):
                        file_path = match.group(1).lstrip("./\\")
                        attachments.append(file_path)

                        if self.config["debug"]:
                            print(f"DEBUG    - FOUND IMAGE: {file_path}")
                        attachments.append("docs/" + file_path.replace("../", ""))

                except AttributeError as e:
                    if self.config["debug"]:
                        print(f"DEBUG    - WARN(({e}): No images found in markdown. Proceed..")
                new_markdown = re.sub(
                    r'<img src="file:///tmp/', '<p><ac:image ac:height="350"><ri:attachment ri:filename="', markdown
                )
                new_markdown = re.sub(r'" style="page-break-inside: avoid;">', '"/></ac:image></p>', new_markdown)
                confluence_body = self.confluence_mistune(new_markdown)
                f.write(confluence_body)
                if self.config["debug"]:
                    print(confluence_body)
                page_name = page.title
                new_name = "confluence_page_" + page_name.replace(" ", "_") + ".html"
                shutil.copy(f.name, new_name)
                f.close()

                if self.config["debug"]:
                    print(
                        f"\nDEBUG    - UPDATING PAGE TO CONFLUENCE, DETAILS:\n"
                        f"DEBUG    - HOST: {self.config['host_url']}\n"
                        f"DEBUG    - SPACE: {self.config['space']}\n"
                        f"DEBUG    - TITLE: {page.title}\n"
                        f"DEBUG    - PARENT: {parent}\n"
                        f"DEBUG    - BODY: {confluence_body}\n"
                    )

                page_id = self.find_page_id(page.title)
                if page_id is not None:
                    if self.config["debug"]:
                        print(
                            f"DEBUG    - JUST ONE STEP FROM UPDATE OF PAGE '{page.title}' \n"
                            f"DEBUG    - CHECKING IF PARENT PAGE ON CONFLUENCE IS THE SAME AS HERE"
                        )

                    parent_name = self.find_parent_name_of_page(page.title)

                    if parent_name == parent:
                        if self.config["debug"]:
                            print("DEBUG    - Parents match. Continue...")
                    else:
                        if self.config["debug"]:
                            print(f"DEBUG    - ERR, Parents does not match: '{parent}' =/= '{parent_name}' Aborting...")
                        return markdown
                    self.update_page(page.title, confluence_body)
                    for i in MkdocsWithConfluence.tab_nav:
                        if page.title in i:
                            print(f"INFO    - Mkdocs With Confluence: {i} *UPDATE*")
                else:
                    if self.config["debug"]:
                        print(
                            f"DEBUG    - PAGE: {page.title}, PARENT0: {parent}, "
                            f"PARENT1: {parent1}, MAIN PARENT: {main_parent}"
                        )
                    parent_id = self.find_page_id(parent)
                    self.wait_until(parent_id, 1, 20)
                    second_parent_id = self.find_page_id(parent1)
                    self.wait_until(second_parent_id, 1, 20)
                    main_parent_id = self.find_page_id(main_parent)
                    if not parent_id:
                        if not second_parent_id:
                            main_parent_id = self.find_page_id(main_parent)
                            if not main_parent_id:
                                print("ERR: MAIN PARENT UNKNOWN. ABORTING!")
                                return markdown

                            if self.config["debug"]:
                                print(
                                    f"DEBUG    - Trying to ADD page '{parent1}' to "
                                    f"main parent({main_parent}) ID: {main_parent_id}"
                                )
                            body = TEMPLATE_BODY.replace("TEMPLATE", parent1)
                            self.add_page(parent1, main_parent_id, body)
                            for i in MkdocsWithConfluence.tab_nav:
                                if parent1 in i:
                                    print(f"INFO    - Mkdocs With Confluence: {i} *NEW PAGE*")
                            time.sleep(1)

                        if self.config["debug"]:
                            print(
                                f"DEBUG    - Trying to ADD page '{parent}' "
                                f"to parent1({parent1}) ID: {second_parent_id}"
                            )
                        body = TEMPLATE_BODY.replace("TEMPLATE", parent)
                        self.add_page(parent, second_parent_id, body)
                        for i in MkdocsWithConfluence.tab_nav:
                            if parent in i:
                                print(f"INFO    - Mkdocs With Confluence: {i} *NEW PAGE*")
                        time.sleep(1)

                    if parent_id is None:
                        for i in range(11):
                            while parent_id is None:
                                try:
                                    self.add_page(page.title, parent_id, confluence_body)
                                except requests.exceptions.HTTPError:
                                    print(
                                        f"ERR    - HTTP error on adding page. It probably occured due to "
                                        f"parent ID('{parent_id}') page is not YET synced on server. Retry nb {i}/10..."
                                    )
                                    sleep(5)
                                    parent_id = self.find_page_id(parent)
                                break

                    self.add_page(page.title, parent_id, confluence_body)

                    print(f"Trying to ADD page '{page.title}' to parent0({parent}) ID: {parent_id}")
                    for i in MkdocsWithConfluence.tab_nav:
                        if page.title in i:
                            print(f"INFO    - Mkdocs With Confluence: {i} *NEW PAGE*")

                if attachments:
                    self.page_attachments[page.title] = attachments

            except IndexError as e:
                if self.config["debug"]:
                    print(f"DEBUG    - ERR({e}): Exception error!")
                return markdown

        return markdown

    def on_post_page(self, output, page, config):
        site_dir = config.get("site_dir")
        attachments = self.page_attachments.get(page.title, [])

        if self.config["debug"]:
            print(f"\nDEBUG    - UPLOADING ATTACHMENTS TO CONFLUENCE FOR {page.title}, DETAILS:")
            print(f"FILES: {attachments}  \n")
        for attachment in attachments:
            if self.config["debug"]:
                print(f"DEBUG    - looking for {attachment} in {site_dir}")
            for p in Path(site_dir).rglob(f"*{attachment}"):
                self.add_or_update_attachment(page.title, p)
        return output

    def on_page_content(self, html, page, config, files):
        return html

    def __get_page_url(self, section):
        return re.search("url='(.*)'\\)", section).group(1)[:-1] + ".md"

    def __get_page_name(self, section):
        return os.path.basename(re.search("url='(.*)'\\)", section).group(1)[:-1])

    def __get_section_name(self, section):
        if self.config["debug"]:
            print(f"DEBUG    - SECTION name: {section}")
        return os.path.basename(re.search("url='(.*)'\\/", section).group(1)[:-1])

    def __get_section_title(self, section):
        if self.config["debug"]:
            print(f"DEBUG    - SECTION title: {section}")
        try:
            r = re.search("Section\\(title='(.*)'\\)", section)
            return r.group(1)
        except AttributeError:
            name = self.__get_section_name(section)
            print(f"WRN    - Section '{name}' doesn't exist in the mkdocs.yml nav section!")
            return name

    def __get_page_title(self, section):
        try:
            r = re.search("\\s*Page\\(title='(.*)',", section)
            return r.group(1)
        except AttributeError:
            name = self.__get_page_url(section)
            print(f"WRN    - Page '{name}' doesn't exist in the mkdocs.yml nav section!")
            return name

    # Adapted from https://stackoverflow.com/a/3431838
    def get_file_sha1(self, file_path):
        hash_sha1 = hashlib.sha1()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_sha1.update(chunk)
        return hash_sha1.hexdigest()

    def add_or_update_attachment(self, page_name, filepath):
        print(f"INFO    - Mkdocs With Confluence * {page_name} *ADD/Update ATTACHMENT if required* {filepath}")
        if self.config["debug"]:
            print(f" * Mkdocs With Confluence: Add Attachment: PAGE NAME: {page_name}, FILE: {filepath}")
        page_id = self.find_page_id(page_name)
        if page_id:
            file_hash = self.get_file_sha1(filepath)
            attachment_message = f"MKDocsWithConfluence [v{file_hash}]"
            existing_attachment = self.get_attachment(page_id, filepath)
            if existing_attachment:
                file_hash_regex = re.compile(r"\[v([a-f0-9]{40})]$")
                existing_match = file_hash_regex.search(existing_attachment["version"]["message"])
                if existing_match is not None and existing_match.group(1) == file_hash:
                    if self.config["debug"]:
                        print(f" * Mkdocs With Confluence * {page_name} * Existing attachment skipping * {filepath}")
                else:
                    self.update_attachment(page_id, filepath, existing_attachment, attachment_message)
            else:
                self.create_attachment(page_id, filepath, attachment_message)
        else:
            if self.config["debug"]:
                print("PAGE DOES NOT EXISTS")

    def get_attachment(self, page_id, filepath):
        name = os.path.basename(filepath)
        if self.config["debug"]:
            print(f" * Mkdocs With Confluence: Get Attachment: PAGE ID: {page_id}, FILE: {filepath}")

        url = self.config["host_url"] + "/" + page_id + "/child/attachment"
        headers = {"X-Atlassian-Token": "no-check"}  # no content-type here!
        if self.config["debug"]:
            print(f"URL: {url}")

        r = self.session.get(url, headers=headers, params={"filename": name, "expand": "version"})
        r.raise_for_status()
        with nostdout():
            response_json = r.json()
        if response_json["size"]:
            return response_json["results"][0]

    def update_attachment(self, page_id, filepath, existing_attachment, message):
        if self.config["debug"]:
            print(f" * Mkdocs With Confluence: Update Attachment: PAGE ID: {page_id}, FILE: {filepath}")

        url = self.config["host_url"] + "/" + page_id + "/child/attachment/" + existing_attachment["id"] + "/data"
        headers = {"X-Atlassian-Token": "no-check"}  # no content-type here!

        if self.config["debug"]:
            print(f"URL: {url}")

        filename = os.path.basename(filepath)

        # determine content-type
        content_type, encoding = mimetypes.guess_type(filepath)
        if content_type is None:
            content_type = "multipart/form-data"
        files = {"file": (filename, open(Path(filepath), "rb"), content_type), "comment": message}

        if not self.dryrun:
            r = self.session.post(url, headers=headers, files=files)
            r.raise_for_status()
            print(r.json())
            if r.status_code == 200:
                print("OK!")
            else:
                print("ERR!")

    def create_attachment(self, page_id, filepath, message):
        if self.config["debug"]:
            print(f" * Mkdocs With Confluence: Create Attachment: PAGE ID: {page_id}, FILE: {filepath}")

        url = self.config["host_url"] + "/" + page_id + "/child/attachment"
        headers = {"X-Atlassian-Token": "no-check"}  # no content-type here!

        if self.config["debug"]:
            print(f"URL: {url}")

        filename = os.path.basename(filepath)

        # determine content-type
        content_type, encoding = mimetypes.guess_type(filepath)
        if content_type is None:
            content_type = "multipart/form-data"
        files = {"file": (filename, open(filepath, "rb"), content_type), "comment": message}
        if not self.dryrun:
            r = self.session.post(url, headers=headers, files=files)
            print(r.json())
            r.raise_for_status()
            if r.status_code == 200:
                print("OK!")
            else:
                print("ERR!")

    def find_page_id(self, page_name):
        if self.config["debug"]:
            print(f"INFO    -   * Mkdocs With Confluence: Find Page ID: PAGE NAME: {page_name}")
        name_confl = page_name.replace(" ", "+")
        url = self.config["host_url"] + "?title=" + name_confl + "&spaceKey=" + self.config["space"] + "&expand=history"
        if self.config["debug"]:
            print(f"URL: {url}")
        r = self.session.get(url)
        r.raise_for_status()
        with nostdout():
            response_json = r.json()
        if response_json["results"]:
            if self.config["debug"]:
                print(f"ID: {response_json['results'][0]['id']}")
            return response_json["results"][0]["id"]
        else:
            if self.config["debug"]:
                print("PAGE DOES NOT EXIST")
            return None

    def add_page(self, page_name, parent_page_id, page_content_in_storage_format):
        print(f"INFO    -   * Mkdocs With Confluence: {page_name} - *NEW PAGE*")

        if self.config["debug"]:
            print(f" * Mkdocs With Confluence: Adding Page: PAGE NAME: {page_name}, parent ID: {parent_page_id}")
        url = self.config["host_url"] + "/"
        if self.config["debug"]:
            print(f"URL: {url}")
        headers = {"Content-Type": "application/json"}
        space = self.config["space"]
        data = {
            "type": "page",
            "title": page_name,
            "space": {"key": space},
            "ancestors": [{"id": parent_page_id}],
            "body": {"storage": {"value": page_content_in_storage_format, "representation": "storage"}},
        }
        if self.config["debug"]:
            print(f"DATA: {data}")
        if not self.dryrun:
            r = self.session.post(url, json=data, headers=headers)
            r.raise_for_status()
            if r.status_code == 200:
                if self.config["debug"]:
                    print("OK!")
            else:
                if self.config["debug"]:
                    print("ERR!")

    def update_page(self, page_name, page_content_in_storage_format):
        page_id = self.find_page_id(page_name)
        print(f"INFO    -   * Mkdocs With Confluence: {page_name} - *UPDATE*")
        if self.config["debug"]:
            print(f" * Mkdocs With Confluence: Update PAGE ID: {page_id}, PAGE NAME: {page_name}")
        if page_id:
            page_version = self.find_page_version(page_name)
            page_version = page_version + 1
            url = self.config["host_url"] + "/" + page_id
            if self.config["debug"]:
                print(f"URL: {url}")
            headers = {"Content-Type": "application/json"}
            space = self.config["space"]
            data = {
                "id": page_id,
                "title": page_name,
                "type": "page",
                "space": {"key": space},
                "body": {"storage": {"value": page_content_in_storage_format, "representation": "storage"}},
                "version": {"number": page_version},
            }

            if not self.dryrun:
                r = self.session.put(url, json=data, headers=headers)
                r.raise_for_status()
                if r.status_code == 200:
                    if self.config["debug"]:
                        print("OK!")
                else:
                    if self.config["debug"]:
                        print("ERR!")
        else:
            if self.config["debug"]:
                print("PAGE DOES NOT EXIST YET!")

    def find_page_version(self, page_name):
        if self.config["debug"]:
            print(f"INFO    -   * Mkdocs With Confluence: Find PAGE VERSION, PAGE NAME: {page_name}")
        name_confl = page_name.replace(" ", "+")
        url = self.config["host_url"] + "?title=" + name_confl + "&spaceKey=" + self.config["space"] + "&expand=version"
        r = self.session.get(url)
        r.raise_for_status()
        with nostdout():
            response_json = r.json()
        if response_json["results"] is not None:
            if self.config["debug"]:
                print(f"VERSION: {response_json['results'][0]['version']['number']}")
            return response_json["results"][0]["version"]["number"]
        else:
            if self.config["debug"]:
                print("PAGE DOES NOT EXISTS")
            return None

    def find_parent_name_of_page(self, name):
        if self.config["debug"]:
            print(f"INFO    -   * Mkdocs With Confluence: Find PARENT OF PAGE, PAGE NAME: {name}")
        idp = self.find_page_id(name)
        url = self.config["host_url"] + "/" + idp + "?expand=ancestors"

        r = self.session.get(url)
        r.raise_for_status()
        with nostdout():
            response_json = r.json()
        if response_json:
            if self.config["debug"]:
                print(f"PARENT NAME: {response_json['ancestors'][-1]['title']}")
            return response_json["ancestors"][-1]["title"]
        else:
            if self.config["debug"]:
                print("PAGE DOES NOT HAVE PARENT")
            return None

    def wait_until(self, condition, interval=0.1, timeout=1):
        start = time.time()
        while not condition and time.time() - start < timeout:
            time.sleep(interval)
