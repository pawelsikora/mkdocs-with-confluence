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

TEMPLATE_BODY = "<p> TEMPLATE </p>"

class MkdocsWithConfluence(BasePlugin):
    _id = 0
    config_scheme = (
        ('host_url', config_options.Type(str, default=None)),
        ('space', config_options.Type(str, default=None)),
        ('parent_page_name', config_options.Type(str, default=None)),
        ('username', config_options.Type(str, default=None)),
        ('password', config_options.Type(str, default=None)),
        ('enabled_if_env', config_options.Type(str, default=None)),
        ('verbose', config_options.Type(bool, default=False)),
        ('debug', config_options.Type(bool, default=False)),
        ('dryrun', config_options.Type(bool, default=False)),
    )

    def __init__(self):
        self.enabled = True
        self.confluence_renderer = ConfluenceRenderer(use_xhtml=True)
        self.confluence_mistune = mistune.Markdown(renderer=self.confluence_renderer)
        self.simple_log = True
        self.flen = 1

    def on_files(self, files, config):
        self.flen = len(files.documentation_pages())
        print(f"Number of Files: {self.flen}")
    
    #def on_pre_template(self, template, template_name, config):
    def on_post_template(self, output_content, template_name, config):
        if self.config['verbose'] is False and self.config['debug'] is False: 
            self.simple_log = True
            print("INFO    -  Mkdocs With Confluence: Start exporting markdown pages... (simple logging)")
        else:
            self.simple_log = False
    def on_config(self, config):
        if 'enabled_if_env' in self.config:
            env_name = self.config['enabled_if_env']
            if env_name:
                self.enabled = os.environ.get(env_name) == '1'
                if not self.enabled:
                    print(
                            'WARNING - Mkdocs With Confluence: Exporting MKDOCS pages to Confluence turned OFF: '
                            f'(set environment variable {env_name} to 1 to enable)'
                        )
                    return
                else:
                    print("INFO    -  Mkdocs With Confluence: Exporting MKDOCS pages to Confluence turned ON by var {env_name}==1!")
                    self.enabled = True
            else:    
                print(
                        'WARNING -  Mkdocs With Confluence: Exporting MKDOCS pages to Confluence turned OFF: '
                        f'(set environment variable {env_name} to 1 to enable)'
                    )
                return
        else:
            print("INFO    -  Mkdocs With Confluence: Exporting MKDOCS pages to Confluence turned ON by default!")
            self.enabled = True
        
        if self.config['dryrun']:
            print("WARNING -  Mkdocs With Confluence - DRYRUN MODE turned ON")
            self.dryrun = True
        else:
            self.dryrun = False

    def on_page_markdown(self, markdown, page, config, files):
        MkdocsWithConfluence._id += 1
        self.pw = self.config['password']
        self.user = self.config['username']
        
        if self.enabled:
            if self.simple_log is True:
                print("INFO    - Mkdocs With Confluence: Page export progress: [", end='', flush=True)
                for i in range(MkdocsWithConfluence._id):
                    print("#", end='', flush=True)
                for j in range(self.flen - MkdocsWithConfluence._id):
                    print("-", end='', flush=True)
                print(f"] ({MkdocsWithConfluence._id} / {self.flen})", end='\r', flush=True)

            if self.config['debug']:
                print(f"\nHandling Page '{page.title}' (And Parent Nav Pages if necessary):\n")
            if not all(self.config_scheme):
                    print("ERR: YOU HAVE EMPTY VALUES IN YOUR CONFIG. ABORTING")
                    return markdown
            try:
                parent = self.__get_section_title(page.ancestors[0].__repr__())
                
                if self.config['parent_page_name'] is not None:
                    main_parent = self.config['parent_page_name']
                else:
                    main_parent = self.config['space']
                
                try:
                    parent1 = self.__get_section_title(page.ancestors[1].__repr__())
                except:
                    parent1 = main_parent
                    if self.config['debug']:
                        print(f"ONLY ONE PARENT FOUND. ASSUMING AS A FIRST NODE after main parent config {main_parent}")
                
                if self.config['debug']:
                    print(f"PARENT0: {parent}, PARENT1: {parent1}, MAIN PARENT: {main_parent}")
                
                tf = tempfile.NamedTemporaryFile(delete=False)
                f = open(tf.name, "w")
                
                files = []
                try:
                    for match in re.finditer(r'img src="file://(.*)" s', markdown):
                        if self.config['debug']:
                            print(f"FOUND IMAGE: {match.group(1)}")
                        files.append(match.group(1))
                except AttributeError:
                    if self.config['debug']:
                        print("WARN: No images found in markdown. Proceed..")

                new_markdown = re.sub(r'<img src="file:///tmp/', '!', markdown)
                new_markdown = re.sub(r'" style="page-break-inside: avoid;">', '!', new_markdown)
                confluence_body = self.confluence_mistune(new_markdown)
                f.write(confluence_body)
                page_name = page.title
                new_name = "confluence_page_" + page_name.replace(" ", "_") + ".html"
                shutil.copy(f.name, new_name)
                f.close()

                if self.config['debug']:
                    print(f"\nUPDATING PAGE TO CONFLUENCE, DETAILS:\n"
                          f"HOST: {self.config['host_url']}\n"
                          f"SPACE: {self.config['space']}\n"
                          f"TITLE: {page.title}\n"
                          f"PARENT: {parent}\n"
                          f"BODY: {confluence_body}\n"
                          )
                
                page_id = self.find_page_id(page.title)
                if page_id is not None:
                    if self.config['debug']:
                        print(f"JUST ONE STEP FROM UPDATE OF PAGE '{page.title}' \n" \
                            f"CHECKING IF PARENT PAGE ON CONFLUENCE IS THE SAME AS HERE")

                    parent_name = self.find_parent_name_of_page(page.title)

                    if parent_name == parent:
                        if self.config['debug']:
                            print(f" - OK, Parents match. Continue...")
                    else:
                        if self.config['debug']:
                            print(f" - ERR, Parents does not match: '{parent}' =/= '{parent_name}' Abort before messing up...")
                        return markdown
                    self.update_page(page.title, confluence_body)
                else:
                    parent_id = self.find_page_id(parent)
                    if not parent_id:
                        if not parent_id:
                            second_parent_id = self.find_page_id(parent1)
                            if not second_parent_id:
                                main_parent_id = self.find_page_id(main_parent)
                                if not main_parent_id:
                                    print("ERR: MAIN PARENT UNKNOWN. ABORTING!")
                                    return markdown
                                body = TEMPLATE_BODY.replace("TEMPLATE", parent1)
                                self.add_page(parent1, main_parent_id, body)
                                #time.sleep(1)
                            body = TEMPLATE_BODY.replace("TEMPLATE", parent)
                            self.add_page(parent, parent_id, body)
                            #time.sleep(1)
                    self.add_page(page.title, parent_id, confluence_body)

                if files:
                    if self.config['debug']:
                        print(f"\nUPLOADING ATTACHMENTS TO CONFLUENCE, DETAILS:\n"
                            f"FILES: {files}\n"
                        )
                    for f in files:
                        self.add_attachment(page.title, f)

            except IndexError:
                return markdown
        
        return markdown

    def on_page_content(self, html, page, config, files):
        return html

    def __get_section_title(self, section):
        return re.search("Section\(title=\'(.*)\'\)", section).group(1)

    def add_attachment(self, page_name, filepath):
        if self.config['verbose']:
            print(f"INFO    -  Mkdocs With Confluence * {page_name} *NEW ATTACHMENT* {filepath}")
        if self.config['debug']:
            print(f" * Mkdocs With Confluence: Add Attachment: PAGE NAME: {page_name}, FILE: {filepath}")
        page_id = self.find_page_id(page_name)
        if page_id:
            url = self.config['host_url'] + "/" + \
                  page_id + '/child/attachment/'
            headers = {'X-Atlassian-Token': 'no-check'} #no content-type here!
            if self.config['debug']:
                print(f"URL: {url}")
            filename = filepath
            auth = (self.user, self.pw)
    
            # determine content-type
            content_type, encoding = mimetypes.guess_type(filename)
            if content_type is None:
                content_type = 'multipart/form-data'
            files = {'file': (filename, open(filename, 'rb'), content_type)}
            
            if not self.dryrun:
                r = requests.post(url, headers=headers, files=files, auth=auth)
                r.raise_for_status()
                if r.status_code == 200:
                    print ('OK!')
                else:
                    print ('ERR!')
        else:
            if self.config['debug']:
                print("PAGE DOES NOT EXISTS")
    
    def find_page_id(self, page_name):
        if self.config['debug']:
            print(f"INFO    -   * Mkdocs With Confluence: Find Page ID: PAGE NAME: {page_name}")
        name_confl = page_name.replace(" ", "+")
        url = self.config['host_url'] + "?title=" + \
              name_confl + '&spaceKey=' + self.config['space'] + \
              '&expand=history'
        if self.config['debug']:
            print(f"URL: {url}")
        auth = (self.user, self.pw)
        r = requests.get(url, auth=auth)
        r.raise_for_status()
        response_json = r.json()
        if response_json["results"]:
            if self.config['debug']:
                print(f"ID: {response_json['results'][0]['id']}")
            return response_json['results'][0]['id']
        else:
            if self.config['debug']:
                print("PAGE DOES NOT EXIST")
            return None
    
    def add_page(self, page_name, parent_page_id, page_content_in_storage_format):
        if self.config['verbose']:
            print(f"INFO    -   * Mkdocs With Confluence: {page_name} - *NEW PAGE*")
        if self.config['debug']:
            print(f" * Mkdocs With Confluence: Adding Page: PAGE NAME: {page_name}, parent ID: {parent_page_id}")
        url = self.config['host_url'] + "/"
        if self.config['debug']:
            print(f"URL: {url}")
        headers = {'Content-Type': 'application/json'}
        auth = (self.user, self.pw)
        space = self.config['space']
        data = {
                "type": "page",
                "title": page_name,
                "space":{"key": space},
                "ancestors": [{"id": parent_page_id}],
                "body":{
                    "storage": {
                            "value": page_content_in_storage_format,
                            "representation": "storage"
                    }
                }
                }
    
        if not self.dryrun:
            r = requests.post(url, json=data, headers=headers, auth=auth)
            r.raise_for_status()
            if r.status_code == 200:
                if self.config['debug']:
                    print ('OK!')
            else:
                if self.config['debug']:
                    print ('ERR!')
    
    def update_page(self, page_name, page_content_in_storage_format):
        page_id = self.find_page_id(page_name)
        if self.config['verbose']:
            print(f"INFO    -   * Mkdocs With Confluence: {page_name} - *UPDATE*")
        if self.config['debug']:
            print(f" * Mkdocs With Confluence: Update PAGE ID: {page_id}, PAGE NAME: {page_name}")
        if page_id:
            page_version = self.find_page_version(page_name)
            page_version = page_version + 1
            url = self.config['host_url'] + "/" + page_id
            if self.config['debug']:
                print(f"URL: {url}")
            pid = f"{page_id}"
            headers = {'Content-Type': 'application/json'}
            auth = (self.user, self.pw)
            data = {
                    "id": page_id,
                    "title": page_name,
                    "type": "page",
                    "space":{"key":"RFSW"},
                    "body":{
                        "storage": {
                                "value": page_content_in_storage_format,
                                "representation": "storage"
                        }
                    },
                    "version":{"number": page_version}
                    }
    
            if not self.dryrun:
                r = requests.put(url, json=data, headers=headers, auth=auth)
                r.raise_for_status()
                if r.status_code == 200:
                    if self.config['debug']:
                        print ('OK!')
                else:
                    if self.config['debug']:
                        print ('ERR!')
        else:
            if self.config['debug']:
                print("PAGE DOES NOT EXIST YET!")
    
    def find_page_version(self, page_name):
        if self.config['debug']:
            print(f"INFO    -   * Mkdocs With Confluence: Find PAGE VERSION, PAGE NAME: {page_name}")
        name_confl = page_name.replace(" ", "+")
        url = self.config['host_url'] + "?title=" + \
              name_confl + '&spaceKey=' + \
              self.config['space'] + '&expand=version'
    
        auth = (self.user, self.pw)
        r = requests.get(url, auth=auth)
        r.raise_for_status()
        response_json = r.json()
        if response_json["results"]:
            if self.config['debug']:
                print(f"VERSION: {response_json['results'][0]['version']['number']}")
            return response_json['results'][0]['version']['number']
        else:
            if self.config['debug']:
                print("PAGE DOES NOT EXISTS")
            return None

    def find_parent_name_of_page(self, name):
        if self.config['debug']:
            print(f"INFO    -   * Mkdocs With Confluence: Find PARENT OF PAGE, PAGE NAME: {name}")
        idp = self.find_page_id(name)
        name_confl = name.replace(" ", "+")
        url = self.config['host_url'] + "/" + idp + "?expand=ancestors"
    
        auth = (self.user, self.pw)
        r = requests.get(url, auth=auth)
        r.raise_for_status()
        response_json = r.json()
        if response_json:
            if self.config['debug']:
                print(f"PARENT NAME: {response_json['ancestors'][0]['title']}")
            return response_json['ancestors'][0]['title']
        else:
            if self.config['debug']:
                print("PAGE DOES NOT HAVE PARENT")
            return None
