#!/usr/local/bin/python

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
            row = [c.text for c in row.getchildren()]
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
            elif toon in ['Tank','Heals','Heals/DPS','DPS']:
                toon = row[2]

            if toon == None:
                continue
            group['toons'].append(toon.encode('utf-8','ignore'))

    if len(group['toons']) != 0:
        jsontext.append(group)

print json.dumps(jsontext)