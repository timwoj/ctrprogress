#!/usr/local/bin/python

# This script takes exported HTML from the CTR master raid group list maintained
# by Knate, parses all of the groups, and outputs a block of JSON suitable for
# loading into the datastore on the CTRRanks site.
from lxml import html
import json
import os

jsontext = list()

for file in os.listdir('.'):
    if file.endswith('html') == False:
        continue
        
    f = open(file,'r')
    text = f.read()
    if 'Disbanded' in text:
        continue
    elif 'Team Information' not in text:
        continue
        
    tree = html.fromstring(text)
    alltrs = tree.xpath("//tbody/tr")

    group = dict()
    group['toons'] = list()
    
    for i,row in enumerate(alltrs):
        if i:
            # break down each <tr> row into the individual <td> children
            # and then get the text from each one of them.  stick that
            # text into a list.
            row = [c.text_content() for c in row.getchildren()]
            if i == 1:
                # there's a few groups that are poorly formed in the HTML
                # data and should just be skipped for simplicity
                if row[2] == None:
                    break
                group['name'] = row[2].encode('utf-8','ignore')
                
            toon = row[4]
            if toon == None:
                continue
            elif toon == 'Aerie Peak':
                toon = row[3]
            elif toon in ['Tank','Heals','Heals/DPS','DPS','DPS/Tank','Bench/Alt']:
                toon = row[2]

            if toon != None and len(toon) != 0:
                group['toons'].append(toon.encode('utf-8','ignore'))

    if len(group['toons']) < 5:
        jsontext.append(group)

print json.dumps(jsontext)
