# Generated from: linkedin_profile.ipynb
# Converted at: 2025-12-20T21:19:24.703Z
# Next step (optional): refactor into modules & generate tests with RunCell
# Quick start: pip install runcell

# ## LinkedIn Profile Scraper in Python


import warnings
warnings.filterwarnings("ignore")

import os
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By

from time import sleep

from dotenv import load_dotenv
load_dotenv()

# if you don't have a .env file, you can create one and add the following lines:
os.environ['EMAIL'] = ''
os.environ['PASSWORD'] = ''

driver = webdriver.Chrome()

driver.get('https://www.linkedin.com/login')

driver.title

email = driver.find_element(By.ID, 'username')
email.send_keys(os.environ['EMAIL'])

password = driver.find_element(By.ID, 'password')
password.send_keys(os.environ['PASSWORD'])

password.submit()

input("Press Enter after login ....")

## MAKE SURE TO USE ONLY THIS URL TO AVOID BEING STUCK IN ERRORS

url = "https://www.linkedin.com/in/laxmimerit"
driver.get(url)

profile_data = {}

driver.title

page_source = driver.page_source
soup = BeautifulSoup(page_source, 'lxml')

name = soup.find('h1', {'class': 'text-heading-xlarge inline t-24 v-align-middle break-words'})

name = name.get_text().strip()

profile_data['name'] = name
profile_data['url'] = url

profile_data

headline = soup.find('div', {'class': 'text-body-medium break-words'})
headline = headline.get_text().strip()

profile_data['headline'] = headline

profile_data

# ### Show More


driver.find_element(By.CLASS_NAME, "inline-show-more-text__button").click()

page_source = driver.page_source
soup = BeautifulSoup(page_source, 'lxml')

about = soup.find('div', {'class': 'display-flex ph5 pv3'})

about = about.get_text().strip()

profile_data['about'] = about

profile_data

# ### Read Experience


page_source = driver.page_source
soup = BeautifulSoup(page_source, 'lxml')

sections = soup.find_all('section', {'class': 'artdeco-card pv-profile-card break-words mt2'})

for sec in sections:
    if sec.find('div', {'id': 'experience'}):
        experience = sec

# print(experience.get_text().strip())

experience = experience.find_all('div', {'class': 'gFJNglFOnyZmIAbxVkrWpQCmMhGSasZRfRtGlFg YcvguSXGGYgEmpWJOhQrhmNocNiIvvDjETE bAMoJMoZyFCvvmHkHNQEBnMuJTWUocrss'})

len(experience)

exp = experience[0]

def get_exp(exp):

    exp_dict = {}

    name = exp.find('div', {'class': 'display-flex flex-wrap align-items-center full-height'})
    name = name.find('span', {'class': 'visually-hidden'})
    name = name.get_text().strip()

    duration = exp.find('span', {'class': 't-14 t-normal'})
    duration = duration.find('span', {'class': 'visually-hidden'})
    duration = duration.get_text().strip()
    duration

    exp_dict['company_name'] = name
    exp_dict['duration'] = duration

    designations = exp.find_all('div', {'class': 'gFJNglFOnyZmIAbxVkrWpQCmMhGSasZRfRtGlFg'})

    item_list = []
    for position in designations:
        spans = position.find_all('span', {'class': 'visually-hidden'})

        item_dict = {}
        item_dict['designation'] = spans[0].get_text().strip()
        item_dict['duration'] = spans[1].get_text().strip()
        item_dict['location'] = spans[2].get_text().strip()

        try:
            item_dict['projects'] = spans[3].get_text().strip()
        except:
            item_dict['projects'] = ""

        item_list.append(item_dict)


    exp_dict['designations'] = item_list

    return exp_dict

item_list = []
for exp in experience:
    item_list.append(get_exp(exp))

profile_data['experience'] = item_list


# profile_data

# ### Education


for sec in sections:
    if sec.find('div', {'id': 'education'}):
        educations = sec

# educations.get_text().strip()

items = educations.find_all('div', {'class': 'gFJNglFOnyZmIAbxVkrWpQCmMhGSasZRfRtGlFg YcvguSXGGYgEmpWJOhQrhmNocNiIvvDjETE bAMoJMoZyFCvvmHkHNQEBnMuJTWUocrss'})

len(items)

def get_edu(item):
    item_dict = {}
    spans = item.find_all('span', {'class': 'visually-hidden'})

    item_dict['college'] = spans[0].get_text().strip()
    item_dict['degree'] = spans[1].get_text().strip()
    item_dict['duration'] = spans[2].get_text().strip()
    item_dict['project'] = spans[3].get_text().strip()

    return item_dict

item_list = []
for item in items:
    item_list.append(get_edu(item))

profile_data['education'] = item_list


# profile_data

# ### Licenses & certifications


driver.find_element(By.ID, "navigation-index-see-all-licenses-and-certifications").click()

page_source = driver.page_source
soup = BeautifulSoup(page_source, 'lxml')

soup = soup.find('section', {'class': 'artdeco-card pb3'})

items = soup.find_all('div', {'class': 'gFJNglFOnyZmIAbxVkrWpQCmMhGSasZRfRtGlFg YcvguSXGGYgEmpWJOhQrhmNocNiIvvDjETE bAMoJMoZyFCvvmHkHNQEBnMuJTWUocrss'})

len(items)

item = items[0]

def get_license(item):
    spans = item.find_all('span', {'class': 'visually-hidden'})

    item_dict = {}
    item_dict['name'] = spans[0].get_text().strip()
    item_dict['institute'] = spans[1].get_text().strip()
    item_dict['issued_date'] = spans[2].get_text().strip()

    return item_dict

item_list = []
for item in items:
    item_list.append(get_license(item))

profile_data['licenses'] = item_list


driver.back()
# profile_data


# ### Projects


driver.find_element(By.ID, "navigation-index-see-all-projects").click()

page_source = driver.page_source
soup = BeautifulSoup(page_source, 'lxml')

soup = soup.find('section', {'class': 'artdeco-card pb3'})

items = soup.find_all('div', {'class': 'gFJNglFOnyZmIAbxVkrWpQCmMhGSasZRfRtGlFg YcvguSXGGYgEmpWJOhQrhmNocNiIvvDjETE bAMoJMoZyFCvvmHkHNQEBnMuJTWUocrss'})

len(items)

item = items[0]

def get_project(item):
    spans = item.find_all('span', {'class': 'visually-hidden'})

    item_dict = {}
    item_dict['project_name'] = spans[0].get_text().strip()
    item_dict['duration'] = spans[1].get_text().strip()
    item_dict['description'] = spans[2].get_text().strip()

    return item_dict

item_list = []
for item in items:
    item_list.append(get_project(item))

profile_data['projects'] = item_list

driver.back()

# ### All Courses


driver.find_element(By.ID, "navigation-index-see-all-courses").click()

page_source = driver.page_source
soup = BeautifulSoup(page_source, 'lxml')

soup = soup.find('section', {'class': 'artdeco-card pb3'})

items = soup.find_all('div', {'class': 'gFJNglFOnyZmIAbxVkrWpQCmMhGSasZRfRtGlFg YcvguSXGGYgEmpWJOhQrhmNocNiIvvDjETE bAMoJMoZyFCvvmHkHNQEBnMuJTWUocrss'})

len(items)

item = items[0]

def get_course(item):
    spans = item.find_all('span', {'class': 'visually-hidden'})

    item_dict = {}
    item_dict['course_name'] = spans[0].get_text().strip()
    try:
        item_dict['associated_with'] = spans[1].get_text().strip()
    except:
        item_dict['associated_with'] = ""

    return item_dict

item_list = []
for item in items:
    item_list.append(get_course(item))

profile_data['courses'] = item_list

driver.back()

# ### Honors & awards


driver.find_element(By.ID, "navigation-index-see-all-honorsandawards").click()

page_source = driver.page_source
soup = BeautifulSoup(page_source, 'lxml')

soup = soup.find('section', {'class': 'artdeco-card pb3'})

items = soup.find_all('span', {'class': 'visually-hidden'})

len(items)

item_list = []
for item in items:
    item_list.append(item.get_text().strip())

profile_data['honors_and_awards'] = item_list

import json

with open('data/profile_data_tutorial.json', 'w') as f:
    json.dump(profile_data, f, indent=4)

driver.back()