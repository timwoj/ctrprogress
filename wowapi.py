# -*- coding: utf-8 -*-
#!/usr/bin/env python

import json
import logging
import os
import time
import base64
import urllib.parse
import requests
import collections
import traceback

from concurrent import futures

import ctrpmodels

# Method that gets called by the threadpool.  This will fill in the toondata
# dict for the requested toon with either data from Battle.net or with an
# error message to display on the page.  This has to be defined at the
# module level so that the threadpool can call it correctly.
def handle_result(name, realm, oauth_token):

    toondata = {}

    url = 'https://us.api.blizzard.com/profile/wow/character/{}/{}?namespace=profile-us&locale=en_US&access_token={}'.format(realm, urllib.parse.quote(name).lower(), oauth_token)
    
    try:
        response = requests.get(url)
    except Exception as e:
        self.handle_request_exception(e, 'profile', toondata)
        return toondata

    # change the json from the response into a dict of data and store it
    # into the toondata object that was passed in.
    jsondata = response.json()

    if not check_response_status(response, jsondata, 'profile', toondata):
        return toondata

    for k,v in jsondata.items():
        if not isinstance(v, collections.Mapping) or 'href' not in v:
            toondata[k] = v

    # We also need the progression for this character so make a second request
    try:
        url = 'https://us.api.blizzard.com/profile/wow/character/{}/{}/encounters/raids?namespace=profile-us&locale=en_US&access_token={}'.format(realm, urllib.parse.quote(name).lower(), oauth_token)
        response = requests.get(url)
    except Exception as e:
        handle_request_exception(e, 'progression', toondata)
        return

    jsondata = response.json()

    if not check_response_status(response, jsondata, 'progression', toondata):
        return toondata

    # TODO: there's probably faster/more pythonic ways to do this. Loop over
    # the raids we want, then loop over the raids in the instance data looking
    # for them. Loop in reverse because the newest raids look like they're
    # always at the end of the array of instances.
    expansion = [e for e in jsondata.get('expansions',[]) if e.get('expansion',{}).get('name','') == ctrpmodels.Constants.expansion]
    if not expansion:
        print('Failed to find data for expansion {} for toon {}'.format(ctrpmodels.Constants.expansion, name))
        return toondata
    
    instances = expansion[0].get('instances',[])
    raid_data = {}
    for raid in ctrpmodels.Constants.raids:
        for i in reversed(instances):
            if i.get('instance',{}).get('name','') == raid.get('name',''):
                raid_data[raid.get('slug','')] = i.get('modes', [])
                break

    toondata['progression'] = raid_data

    return toondata

# Handles exceptions from requests to the API in a common fashion
def handle_request_exception(exception, where, toondata):
    name = toondata.get('name','')
    toondata['load_status'] = 'nok'
    
    if isinstance(requests.exceptions.Timeout, exception):
        print('requests threw DeadlineExceededError on toon %s' % name.encode('ascii', 'ignore'))
        toondata['reason'] = 'Timeout retrieving %s data from Battle.net for %s.  Refresh page to try again.' % (where, name)
    elif isinstance(requests.exceptions.ConnectionError, exception):
        print('requests threw ConnectionError on toon %s' % name.encode('ascii', 'ignore'))
        toondata['reason'] = 'Connection error retrieving %s data from Battle.net for toon %s.  Refresh page to try again.' % (where, name)
    else:
        print('requests threw unknown exception on toon %s' % name.encode('ascii', 'ignore'))
        toondata['reason'] = 'Unknown error retrieving %s data from Battle.net for toon %s.  Refresh page to try again.' % (where, name)
        
# Checks response codes and error messages from the API in a common fashion.
def check_response_status(response, jsondata, where, toondata):
    if response.status_code != requests.codes.ok or ( 'code' in jsondata and 'detail' in jsondata ):
        code = jsondata.get('code', response.status_code)
        print('requests returned a %d status code on toon %s' % (code, toondata['name'].encode('ascii', 'ignore')))
        toondata['load_status'] = 'nok'
        toondata['reason'] = 'Got a %d requesting %s from Battle.net for toon %s.  Refresh page to try again.' % (code, where, toondata['name'])
        
        if 'detail' in jsondata:
            toondata['reason'] += ' (reason: %s)' % jsondata['detail']
            
        return False
        
    return True


class Importer(object):

    def __init__(self):
        self.oauth_token = self.get_oauth_token()
        if not self.oauth_token:
            raise Exception("Failed to initialize oauth token")

    def get_oauth_token(self):

        path = os.path.join(os.path.split(__file__)[0], 'api-auth.json')
        authdata = json.load(open(path))
        
        credentials = "{}:{}".format(authdata['blizzard_client_id'],
                                     authdata['blizzard_client_secret'])
        encoded_credentials = base64.urlsafe_b64encode(credentials.encode('utf-8'))
        headers = {
            'Authorization': 'Basic {}'.format(str(encoded_credentials, 'utf-8'))
        }
        
        response = requests.post('https://us.battle.net/oauth/token',
                                 data={'grant_type':'client_credentials'},
                                 headers=headers)
        
        if response.status_code == requests.codes.ok:
            response_data = response.json()
            oauth_token = response_data['access_token']

        if not oauth_token:
            return None

        return oauth_token

    def load(self, toonlist):

        data = []
        start = time.time()

        # Create a threadpool to use to make the URL requests to the Blizzard
        # API. This used to use the urlfetch async methods but I need finer
        # control over how many are running at a time since I'm bumping against
        # the API's quotas for free accounts.
        with futures.ThreadPoolExecutor(max_workers=7) as executor:
            fs = {}

            # Request all of the toon data from the blizzard API and determine the
            # group's ilvls, armor type counts and token type counts.  subs are not
            # included in the counts, since they're not really part of the main
            # group.
            for toon in toonlist:
                realm = 'aerie-peak'
                if '/' in toon:
                    (toon, realm) = toon.split('/')
                    # normalize the realm name
                    realm = realm.lower().replace('\'', '').replace(' ', '-')
                fs[executor.submit(handle_result, toon, realm, self.oauth_token)] = toon

            # Loop through all of the futures created above and handle each one as
            # they complete.  The return value from the future is the toon data.
            for future in futures.as_completed(fs):
                toon = fs[future]
                try:
                    if future.exception():
                        print('future for {} had exception {}'.format(toon, future.exception()))
                        raise future.exception()
                    
                    result = future.result()
                    print(result.get('name',''))
                    data.append(future.result())
                except Exception as exc:
                    logging.info("wowapi generated exception for %s: %s", toon, exc)

        end = time.time()

        logging.info("Time spent retrieving data: %f seconds", (end-start))

        return data
