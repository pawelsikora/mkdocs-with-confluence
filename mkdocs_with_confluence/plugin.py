import time
import os
import re
import tempfile
import shutil
import requests
import mimetypes
import mistune
from mkdocs.config import config_options
from mkdocs.plugins import BasePlugin
from md2cf.confluence_renderer import ConfluenceRenderer
from os import environ

TEMPLATE_BODY = "<p> TEMPLATE </p>"


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
        self.confluence_renderer = ConfluenceRenderer(use_xhtml=True)
        self.confluence_mistune = mistune.Markdown(renderer=self.confluence_renderer)
        self.simple_log = False
        self.flen = 1

    def on_nav(self, nav, config, files):
        MkdocsWithConfluence.tab_nav = []
        navigation_items = nav.__repr__()
        for n in navigation_items.split("\n"):
            # print(f"* {n}")
            leading_spaces = len(n) - len(n.lstrip(" "))
            spaces = leading_spaces * " "
            if "Page" in n:
                p = spaces + self.__get_page_title(n)
                MkdocsWithConfluence.tab_nav.append(p)
            if "Section" in n:
                s = spaces + self.__get_section_title(n)
                MkdocsWithConfluence.tab_nav.append(s)

    def on_files(self, files, config):
        pages = files.documentation_pages()
        self.flen = len(pages)
        print(f"Number of Files: {self.flen}")

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
                        "turned ON by var {env_name}==1!"
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
        self.pw = self.config["password"]
        self.user = self.config["username"]

        if self.enabled:
            if self.simple_log is True:
                print("INFO    - Mkdocs With Confluence: Page export progress: [", end="", flush=True)
                for i in range(MkdocsWithConfluence._id):
                    print("#", end="", flush=True)
                for j in range(self.flen - MkdocsWithConfluence._id):
                    print("-", end="", flush=True)
                print(f"] ({MkdocsWithConfluence._id} / {self.flen})", end="\r", flush=True)

            if self.config["verbose"]:
                print(f"\nHandling Page '{page.title}' (And Parent Nav Pages if necessary):\n")
            if not all(self.config_scheme):
                print("ERR: YOU HAVE EMPTY VALUES IN YOUR CONFIG. ABORTING")
                return markdown

            try:
                if self.config["verbose"]:
                    print("Get section first parent title...: ")
                try:
                    parent = self.__get_section_title(page.ancestors[0].__repr__())
                except IndexError as e:
                    print(
                        f'ERR({e}): No second parent! Assuming self.config["parent_page_name"]'
                        f"{self.config['parent_page_name']}..."
                    )
                    parent = None
                if self.config["verbose"]:
                    print(f"{parent}")
                if not parent:
                    parent = self.config["parent_page_name"]

                if self.config["parent_page_name"] is not None:
                    main_parent = self.config["parent_page_name"]
                else:
                    main_parent = self.config["space"]

                if self.config["verbose"]:
                    print("Get section second parent title...: ")
                try:
                    parent1 = self.__get_section_title(page.ancestors[1].__repr__())
                except IndexError as e:
                    print(f"ERR({e}) No second parent! Assuming second parent is main parent: {main_parent}...")
                    parent1 = None
                if self.config["verbose"]:
                    print(f"{parent}")

                if not parent1:
                    parent1 = main_parent
                    if self.config["verbose"]:
                        print(f"ONLY ONE PARENT FOUND. ASSUMING AS A FIRST NODE after main parent config {main_parent}")

                if self.config["verbose"]:
                    print(f"PARENT0: {parent}, PARENT1: {parent1}, MAIN PARENT: {main_parent}")

                tf = tempfile.NamedTemporaryFile(delete=False)
                f = open(tf.name, "w")

                files = []
                try:
                    for match in re.finditer(r'img src="file://(.*)" s', markdown):
                        if self.config["debug"]:
                            print(f"FOUND IMAGE: {match.group(1)}")
                        files.append(match.group(1))
                except AttributeError as e:
                    if self.config["debug"]:
                        print(f"WARN(({e}): No images found in markdown. Proceed..")

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
                        f"\nUPDATING PAGE TO CONFLUENCE, DETAILS:\n"
                        f"HOST: {self.config['host_url']}\n"
                        f"SPACE: {self.config['space']}\n"
                        f"TITLE: {page.title}\n"
                        f"PARENT: {parent}\n"
                        f"BODY: {confluence_body}\n"
                    )

                page_id = self.find_page_id(page.title)
                if page_id is not None:
                    if self.config["debug"]:
                        print(
                            f"JUST ONE STEP FROM UPDATE OF PAGE '{page.title}' \n"
                            f"CHECKING IF PARENT PAGE ON CONFLUENCE IS THE SAME AS HERE"
                        )

                    parent_name = self.find_parent_name_of_page(page.title)

                    if parent_name == parent:
                        if self.config["debug"]:
                            print(" - OK, Parents match. Continue...")
                    else:
                        if self.config["debug"]:
                            print(f" - ERR, Parents does not match: '{parent}' =/= '{parent_name}' Aborting...")
                        return markdown
                    self.update_page(page.title, confluence_body)
                    for i in MkdocsWithConfluence.tab_nav:
                        if page.title in i:
                            n_kol = len(i + " *NEW PAGE*")
                            print(f"INFO    - Mkdocs With Confluence: {i} *UPDATE*")
                else:
                    # if self.config['debug']:
                    print(f"PAGE: {page.title}, PARENT0: {parent}, PARENT1: {parent1}, MAIN PARENT: {main_parent}")
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

                            # if self.config['debug']:
                            print(f"Trying to ADD page '{parent1}' to main parent({main_parent}) ID: {main_parent_id}")
                            body = TEMPLATE_BODY.replace("TEMPLATE", parent1)
                            self.add_page(parent1, main_parent_id, body)
                            for i in MkdocsWithConfluence.tab_nav:
                                if parent1 in i:
                                    n_kol = len(i + "INFO    - Mkdocs With Confluence:" + " *NEW PAGE*")
                                    print(f"INFO    - Mkdocs With Confluence: {i} *NEW PAGE*")
                            time.sleep(1)

                        # if self.config['debug']:
                        print(f"Trying to ADD page '{parent}' to parent1({parent1}) ID: {second_parent_id}")
                        body = TEMPLATE_BODY.replace("TEMPLATE", parent)
                        self.add_page(parent, second_parent_id, body)
                        for i in MkdocsWithConfluence.tab_nav:
                            if parent in i:
                                n_kol = len(i + "INFO    - Mkdocs With Confluence:" + " *NEW PAGE*")
                                print(f"INFO    - Mkdocs With Confluence: {i} *NEW PAGE*")
                        time.sleep(1)

                    # if self.config['debug']:
                    print(f"Trying to ADD page '{page.title}' to parent0({parent}) ID: {parent_id}")
                    self.add_page(page.title, parent_id, confluence_body)
                    for i in MkdocsWithConfluence.tab_nav:
                        if page.title in i:
                            n_kol = len(i + "INFO    - Mkdocs With Confluence:" + " *NEW PAGE*")
                            print(f"INFO    - Mkdocs With Confluence: {i} *NEW PAGE*")

                if files:
                    if self.config["debug"]:
                        print(f"\nUPLOADING ATTACHMENTS TO CONFLUENCE, DETAILS:\n" f"FILES: {files}\n")

                    print(f"\033[A\033[F\033[{n_kol}G  *NEW ATTACHMENTS({len(files)})*")
                    for f in files:
                        self.add_attachment(page.title, f)

            except IndexError as e:
                print(f"ERR({e}): Exception error!")
                return markdown

        return markdown

    def on_page_content(self, html, page, config, files):
        return html

    def __get_section_title(self, section):
        return re.search("Section\\(title='(.*)'\\)", section).group(1)

    def __get_page_title(self, section):
        return re.search("\\s*Page\\(title='(.*)',", section).group(1)

    def add_attachment(self, page_name, filepath):
        if self.config["verbose"]:
            print(f"INFO    - Mkdocs With Confluence * {page_name} *NEW ATTACHMENT* {filepath}")
        if self.config["debug"]:
            print(f" * Mkdocs With Confluence: Add Attachment: PAGE NAME: {page_name}, FILE: {filepath}")
        page_id = self.find_page_id(page_name)
        if page_id:
            url = self.config["host_url"] + "/" + page_id + "/child/attachment/"
            headers = {"X-Atlassian-Token": "no-check"}  # no content-type here!
            if self.config["debug"]:
                print(f"URL: {url}")
            filename = filepath
            auth = (self.user, self.pw)

            # determine content-type
            content_type, encoding = mimetypes.guess_type(filename)
            if content_type is None:
                content_type = "multipart/form-data"
            files = {"file": (filename, open(filename, "rb"), content_type)}

            if not self.dryrun:
                r = requests.post(url, headers=headers, files=files, auth=auth)
                r.raise_for_status()
                if r.status_code == 200:
                    print("OK!")
                else:
                    print("ERR!")
        else:
            if self.config["debug"]:
                print("PAGE DOES NOT EXISTS")

    def find_page_id(self, page_name):
        if self.config["debug"]:
            print(f"INFO    -   * Mkdocs With Confluence: Find Page ID: PAGE NAME: {page_name}")
        name_confl = page_name.replace(" ", "+")
        url = self.config["host_url"] + "?title=" + name_confl + "&spaceKey=" + self.config["space"] + "&expand=history"
        if self.config["debug"]:
            print(f"URL: {url}")
        auth = (self.user, self.pw)
        r = requests.get(url, auth=auth)
        r.raise_for_status()
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
        # if self.config['verbose']:
        #    print(f"INFO    -   * Mkdocs With Confluence: {page_name} - *NEW PAGE*")

        if self.config["debug"]:
            print(f" * Mkdocs With Confluence: Adding Page: PAGE NAME: {page_name}, parent ID: {parent_page_id}")
        url = self.config["host_url"] + "/"
        if self.config["debug"]:
            print(f"URL: {url}")
        headers = {"Content-Type": "application/json"}
        auth = (self.user, self.pw)
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
            r = requests.post(url, json=data, headers=headers, auth=auth)
            r.raise_for_status()
            if r.status_code == 200:
                if self.config["debug"]:
                    print("OK!")
            else:
                if self.config["debug"]:
                    print("ERR!")

    def update_page(self, page_name, page_content_in_storage_format):
        page_id = self.find_page_id(page_name)
        if self.config["verbose"]:
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
            auth = (self.user, self.pw)
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
                r = requests.put(url, json=data, headers=headers, auth=auth)
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

        auth = (self.user, self.pw)
        r = requests.get(url, auth=auth)
        r.raise_for_status()
        response_json = r.json()
        if response_json["results"]:
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

        auth = (self.user, self.pw)
        r = requests.get(url, auth=auth)
        r.raise_for_status()
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
