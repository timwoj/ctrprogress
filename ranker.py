# -*- coding: utf-8 -*-
#!/usr/bin/env python

# External imports
import os
import datetime
import json
import time
import logging
import urllib.parse

from flask import render_template, redirect

# Imports from google
from google.cloud import tasks
from google.cloud import datastore

# Internal imports
import wowapi
import ctrpmodels
from ctrpmodels import Constants

PROJECT_NAME='ctrptest'
PROJECT_REGION='us-central1'

task_client = tasks.CloudTasksClient()
default_queue = task_client.queue_path(PROJECT_NAME, PROJECT_REGION, 'default')
check_queue = task_client.queue_path(PROJECT_NAME, PROJECT_REGION, 'taskcheck')

dcl = datastore.Client()
importer = wowapi.Importer()

def run_builder(request):

    groupname = request.args.get('group')
    if groupname == 'ctrp-taskcheck':

        # Grab the default queue and keep checking for whether or not
        # all of the tasks have finished.
        tasks = task_client.list_tasks(default_queue)

        # This is a hack because list_tasks returns an iterator, which we can't
        # get a length from. This loops through the iterator and sums up how
        # many elements are in it.
        num_tasks = sum(1 for _ in tasks)

        while num_tasks > 0:
            print("task check: waiting for {} tasks to finish".format(num_tasks))
            time.sleep(5)
            tasks = task_client.list_tasks(default_queue)
            num_tasks = sum(1 for _ in tasks)

        response = ''

    else:

        query = dcl.query(kind='Group', filters=[('normalized','=',groupname)])

        if query:
            results = list(query.fetch(limit=1))

        # sanity check, tho this shouldn't be possible
        if not results:
            print('Builder failed to find group {}'.format(groupname))
            return '', 404

        print('Builder task for {} started'.format(groupname))
        response = process_group(results[0], True)
        print('Builder task for {} completed'.format(groupname))

    return response, 200

def process_group(group, write_to_db):

    data = importer.load(group.get('toons',[]))
    progress = ctrpmodels.build_raid_arrays()
    for raid in Constants.raids:
        parse(raid.get('slug', ''), raid.get('bosses', []), data, progress)

    # calculate the avg ilvl values from the toon data
    avgilvl = 0
    numtoons = 0
    for toon in data:
        if toon.get('level', 0) == Constants.max_level and 'equipped_item_level' in toon:
            numtoons += 1
            avgilvl += toon.get('equipped_item_level', 0)

    if numtoons != 0:
        avgilvl /= numtoons

    group.update({'avgilvl': (int(avgilvl) * 100) / 100.0})

    killed_today = {}

    # Loop through the raids that are being processed for this tier and
    # build all of the points of data that are needed.  First, update which
    # bosses have been killed for a group, then loop through the
    # difficulties and build the killed counts and the history.
    for raid in Constants.raids:

        slug = raid.get('slug', '')
        group_raid = group.get('raids', {}).get(slug, {})
        data_raid = progress.get(slug, {})
        boss_count = len(group_raid.get('Normal', []))

        for diff in Constants.difficulties:
            diff_count = 0
            for idx, group_boss in enumerate(group_raid.get(diff, [])):
                if not group_boss and data_raid.get(diff,[])[idx]:
                    if slug not in killed_today:
                        killed_today[slug] = {}
                    if diff not in killed_today[slug]:
                        killed_today[slug][diff] = []
                    killed_today[slug][diff].append(raid.get('bosses',[])[idx])
                    print('new {} kill of {}'.format(diff, raid.get('bosses',[])[idx]))
                    diff_count += 1
                elif group_boss:
                    diff_count += 1

            if slug in killed_today and diff in killed_today.get(slug, {}):
                killed_today[slug]['boss_count'] = boss_count
                killed_today[slug]['{}_kills'.format(diff)] = diff_count

    if len(killed_today) != 0:

        new_hist = {
            'group': group.get('group'),
            'date': datetime.datetime.now(),
            'kills': killed_today
        }
        print(new_hist)

        group.update({'has_kills': True})

        if write_to_db:
            key = dcl.key('History')
            entity = datastore.Entity(key=key)
            entity.update(new_hist)
            dcl.put(entity)

    group.update({'sort_key': ctrpmodels.get_sort_key(group)})
    group.update({'raids': progress})

    if write_to_db:
        dcl.put(group)

    print('Finished building group {}'.format(group.get('group')))
    return '{} data generated<br/>'.format(group.get('group'))

def parse(raidkey, bosses, toondata, progress):

    bossdata = dict()
    for boss in bosses:
        bossdata[boss] = dict()
        for diff in Constants.difficulties:
            bossdata[boss][diff] = dict()
            bossdata[boss][diff]['times'] = list()
            bossdata[boss][diff]['timeset'] = set()

    # loop through each toon in the data from the blizzard API
    for toon in toondata:

        print('Kill data for {}'.format(toon.get('name')))
        # get just the raid data we're looking for in this pass for this one toon
        raid = toon.get('progression',{}).get(raidkey, {})

        # loop through the difficulties because that's the way that blizzard
        # orders them, and it'll make it easier to process.
        for diff in Constants.difficulties:

            encounters = [e for e in raid if e.get('difficulty',{}).get('name') == diff]
            if encounters:
                encounters = encounters[0].get('progress',{}).get('encounters',[])

                for boss in bosses:

                    single_boss = [b for b in encounters if b.get('encounter',{}).get('name','') == boss]
                    if not single_boss:
                        print('{} {} was never killed'.format(diff, boss))
                        continue

                    last_kill = round_time(single_boss[0].get('last_kill_timestamp', 0))
                    bossdata[boss][diff]['times'].append(last_kill)
                    bossdata[boss][diff]['timeset'].add(last_kill)

    # loop back through the difficulties and bosses and build up the
    # progress data
    for idx, boss in enumerate(bosses):

        if boss not in bossdata:
            continue

        for diff in Constants.difficulties:
            # for each boss, grab the set of unique timestamps and sort it
            # with the last kill first
            timelist = list(bossdata[boss][diff]['timeset'])
            timelist.sort(reverse=True)
            print("kill times for {} {}: {}".format(diff, boss, str(timelist)))

            for stamp in timelist:
                count = bossdata[boss][diff]['times'].count(stamp)
                print('{}: time: {}   count: {}'.format(boss, stamp, count))
                if count >= 5:
                    progress[raidkey][diff][idx] = stamp
                    break

def loadone(request):
    groupname = request.args.get('group', '')
    print('loading single {}'.format(groupname))
    query = dcl.query(kind='Group', filters=[('group','=',groupname)])

    if query:
        results = list(query.fetch(limit=1))
        if results:
            return process_group(results[0], True), 200

    return '', 404

def rank():
    tasks = task_client.list_tasks(default_queue)
    num_tasks = sum(1 for _ in tasks)

    template_values = {
        'tasks': num_tasks
    }

    return render_template('ranker.html', **template_values)

def start_ranking():
    # refuse to start the tasks if there are some already running
    tasks = task_client.list_tasks(default_queue)
    num_tasks = sum(1 for _ in tasks)

    epoch = datetime.datetime.now() - datetime.datetime.utcfromtimestamp(0)
    epoch = int(epoch.total_seconds())

    if num_tasks == 0:

        # queue up all of the groups into individual tasks.  the configuration
        # in queue.yaml only allows 10 tasks to run at once.  the builder only
        # allows 10 URL requests at a time, which should hopefully keep the
        # Blizzard API queries under control.
        groups = dcl.query(kind='Group').fetch()
        for group in groups:
            task = {
                'name': task_client.task_path(PROJECT_NAME, PROJECT_REGION, 'default',
                                              '{}-{}'.format(group.get('normalized'), epoch)),
                'app_engine_http_request': {
                    'http_method': 'POST',
                    'relative_uri': '/builder?group={}'.format(group.get('normalized'))
                }
            }

            task_client.create_task(default_queue, task);

        task = {
            'name': task_client.task_path(PROJECT_NAME, PROJECT_REGION,
                                          'taskcheck', 'ctrp-taskcheck-{}'.format(epoch)),
            'app_engine_http_request': {
                'http_method': 'POST',
                'relative_uri': '/builder?group=ctrp-taskcheck'
            }
        }

        task_client.create_task(check_queue, task)

    return redirect('/rank')

# Round a time from the Blizzard API to the nearest 60 seconds because sometimes
# timestamps for the same kill won't be exactly the same. Yes, this is dumb.
#
# Adapted from https://stackoverflow.com/a/10854034/1431079. Takes a timestamp in
# milliseconds directly from the API.
def round_time(timestamp):

    round_to = 60
    dt = datetime.datetime.utcfromtimestamp(timestamp / 1000)
    seconds = (dt.replace(tzinfo=None) - dt.min).seconds
    rounding = (seconds+round_to/2) // round_to * round_to
    rounded = dt + datetime.timedelta(0, rounding-seconds, -dt.microsecond)
    return (rounded - datetime.datetime.utcfromtimestamp(0)).total_seconds() * 1000
