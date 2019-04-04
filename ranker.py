# -*- coding: utf-8 -*-
#!/usr/bin/env python

# External imports
import os
import datetime
import json
import time
import logging
import twitter

from flask import render_template, redirect

# Imports from google
from google.appengine.api import taskqueue
from google.appengine.api.taskqueue import Queue
from google.appengine.api.taskqueue import Task

# Internal imports
import wowapi
from ctrpmodels import Constants
from ctrpmodels import Group
import ctrpmodels

def run_builder(request):
    groupname = request.form.get('group')
    if groupname == 'ctrp-taskcheck':

        # Grab the default queue and keep checking for whether or not
        # all of the tasks have finished.
        default_queue = Queue()
        stats = default_queue.fetch_statistics()
        while stats.tasks > 0:
            logging.info("task check: waiting for %d tasks to finish" % stats.tasks)
            time.sleep(5)
            stats = default_queue.fetch_statistics()

        finish_building()
        response = ''

    else:

        group = Group.get_group_by_name(groupname)

        # sanity check, tho this shouldn't be possible
        if not group:
            logging.info('Builder failed to find group %s' % groupname)
            return '', 404

        logging.info('Builder task for %s started' % groupname)
        importer = wowapi.Importer()
        response = process_group(group, importer, True)
        logging.info('Builder task for %s completed' % groupname)

    return response, 200

def process_group(group, importer, writeDB):
    logging.info('Starting work on group %s' % group.name)

    data = list()
    importer.load(group.toons, data)

    progress = dict()
    parse(Constants.bodbosses, data, Constants.bodname, progress, writeDB)

    # calculate the avg ilvl values from the toon data
    group.avgilvl = 0
    numtoons = 0
    for toon in data:
        # ignore toons that we didn't get data back for or for toons less than
        # level 120
        if 'items' in toon and toon['level'] == 120:
            numtoons += 1
            group.avgilvl += toon['items']['averageItemLevelEquipped']

    if numtoons != 0:
        group.avgilvl /= numtoons

    # update the entry in ndb with the new progression data for this
    # group.  this also checks to make sure that the progress only ever
    # increases, in case of weirdness with the data.  also generate
    # history data while we're at it.
    new_hist = None

    # Loop through the raids that are being processed for this tier and
    # build all of the points of data that are needed.  First, update which
    # bosses have been killed for a group, then loop through the
    # difficulties and build the killed counts and the history.
    for raid in Constants.raids:

        group_raid = getattr(group, raid[0])
        data_raid = progress[raid[1]]

        killedtoday = dict()
        killedtoday['normal'] = list()
        killedtoday['heroic'] = list()
        killedtoday['mythic'] = list()

        for group_boss in group_raid.bosses:
            data_boss = [b for b in data_raid if b.name == group_boss.name][0]
            if data_boss.normaldead != None and group_boss.normaldead == None:
                killedtoday['normal'].append(data_boss.name)
                group_boss.normaldead = data_boss.normaldead
                logging.debug('new normal kill of %s' % data_boss.name)
            if data_boss.heroicdead != None and group_boss.heroicdead == None:
                killedtoday['heroic'].append(data_boss.name)
                group_boss.heroicdead = data_boss.heroicdead
                logging.debug('new heroic kill of %s' % data_boss.name)
            if data_boss.mythicdead != None and group_boss.mythicdead == None:
                killedtoday['mythic'].append(data_boss.name)
                group_boss.mythicdead = data_boss.mythicdead
                logging.debug('new mythic kill of %s' % data_boss.name)

        for d in Constants.difficulties:
            old = getattr(group_raid, d)
            new = len([b for b in group_raid.bosses if getattr(b, d+'dead') != None])
            if old < new:
                if (new_hist == None):
                    new_hist = ctrpmodels.History(group=group.name)
                    new_hist.date = datetime.date.today()
                    new_hist.bod = ctrpmodels.RaidHistory()
                    new_hist.bod.mythic = list()
                    new_hist.bod.heroic = list()
                    new_hist.bod.normal = list()

                raidhist = getattr(new_hist, raid[0])

                raiddiff = getattr(raidhist, d)
                raiddiff = killedtoday[d]

                # These aren't necessary unless a new object is created above
                setattr(raidhist, d+'_total', new)
                setattr(raidhist, d, raiddiff)
                setattr(new_hist, raid[0], raidhist)

                setattr(group_raid, d, new)

    if writeDB:
        group.put()
        if new_hist != None:
            new_hist.put()

    logging.info('Finished building group %s' % group.name)
    return '%s data generated<br/>' % group.name

def parse(bosses, toondata, raidname, progress, writeDB):

    progress[raidname] = list()

    bossdata = dict()
    for boss in bosses:
        bossdata[boss] = dict()
        for d in Constants.difficulties:
            bossdata[boss][d] = dict()
            bossdata[boss][d]['times'] = list()
            bossdata[boss][d]['timeset'] = set()

    # loop through each toon in the data from the blizzard API
    for toon in toondata:

        if 'progression' not in toon:
            continue

        # get just the raid data for this toon
        raids = toon['progression']['raids']

        # this filters the raid data down to just the raid we're looking
        # at this pass
        raid = [d for d in raids if d['name'] == raidname][0]

        # loop through the individual bosses and get the timestamp for
        # the last kill for this toon for each boss
        for boss in bosses:

            # this filters the raid data down to just a single boss
            single_boss = None
            filtered_bosses = [d for d in raid['bosses'] if d['name'] == boss]
            if filtered_bosses:
                single_boss = filtered_bosses[0]

            if not single_boss:
                logging.error('Failed to find boss %s in toon progression data' % boss)
                continue

            # loop through each difficulty level and grab each timestamp.
            # skip any timestamps of zero.  that means the toon never
            # killed the boss.
            for d in Constants.difficulties:
                if single_boss[d+'Timestamp'] != 0:
                    bossdata[boss][d]['times'].append(single_boss[d+'Timestamp'])
                    bossdata[boss][d]['timeset'].add(single_boss[d+'Timestamp'])

    # loop back through the difficulties and bosses and build up the
    # progress data
    for boss in bosses:

        bossobj = ctrpmodels.Boss(name = boss)

        for d in Constants.difficulties:
            # for each boss, grab the set of unique timestamps and sort it
            # with the last kill first
            timelist = list(bossdata[boss][d]['timeset'])
            timelist.sort(reverse=True)
            logging.info("kill times for %s %s: %s" % (d, boss, str(timelist)))

            for t in timelist:
                count = bossdata[boss][d]['times'].count(t)
                logging.info('%s: time: %d   count: %s' % (boss, t, count))
                if count >= 8:
                    logging.info('*** found valid kill for %s %s at %d' % (d, boss, t))
                    setattr(bossobj, d+'dead', datetime.date.today())
                    break

        progress[raidname].append(bossobj)

def finish_building():

    # update the last updated for the whole dataset.  don't actually
    # have to set the time here, the auto_now flag on the property does
    # it for us.
    last_updated = ctrpmodels.Global.get_last_updated()
    if last_updated:
        g = last_updated
        g.put()
    else:
        g = ctrpmodels.Global()

    # post any changes that happened with the history to twitter
    curdate = datetime.date.today()

    # query for all of the history updates for today that haven't been
    # tweeted yet sorted by group name
    updates = ctrpmodels.History.get_not_tweeted(curdate)

    if updates:
        path = os.path.join(os.path.split(__file__)[0],'api-auth.json')
        json_data = json.load(open(path))

        tw_client = twitter.Api(
            consumer_key=json_data['twitter_consumer_key'],
            consumer_secret=json_data['twitter_consumer_secret'],
            access_token_key=json_data['twitter_access_token'],
            access_token_secret=json_data['twitter_access_secret'],
            cache=None)

        template = 'CtR group <%s> killed %d new boss(es) in %s %s to be %d/%d%s!'
        template_start = 'CtR group <%s> killed %d new boss'
        template_end = ' in %s %s to be %d/%d%s!'
        for u in updates:

            # mark this update as tweeted to avoid reposts
            u.tweeted = True

            for raid in Constants.raids:

                raidhist=getattr(u, raid[0])
                if raidhist != None:
                    for d in reversed(Constants.difficulties):

                        kills = getattr(raidhist, d)
                        total = getattr(raidhist, d+'_total')
                        if len(kills) != 0:
                            text = template_start % (u.group, len(kills))
                            if len(kills) > 1:
                                text += "es"
                            text+= template_end % (d.title(), raid[1], total,
                                                   len(raid[2]), d.title()[0])
                            if (d != 'normal') and total == len(raid[2]):
                                text = text + ' #aotc'

#                            tw_client.PostUpdate(text)

            # update the entry in the database so that the tweeted flag
            # gets set to true
            u.put()

def loadone(request):
    groupname = request.args.get('group', '')
    logging.info('loading single %s' % groupname)
    group = Group.get_group_by_name(groupname)
    if group:
        importer = wowapi.Importer()
        process_group(group, importer, False)

    return '', 200

def rank():
    queue = Queue()
    stats = queue.fetch_statistics()

    template_values = {
        'tasks': stats.tasks,
        'in_flight': stats.in_flight,
    }

    return render_template('ranker.html', **template_values)

def start_ranking():
    # refuse to start the tasks if there are some already running
    queue = Queue()
    stats = queue.fetch_statistics()
    if stats.tasks == 0:

        # queue up all of the groups into individual tasks.  the configuration
        # in queue.yaml only allows 10 tasks to run at once.  the builder only
        # allows 10 URL requests at a time, which should hopefully keep the
        # Blizzard API queries under control.
        groups = Group.query().fetch()
        for g in groups:
            taskqueue.add(url='/builder', params={'group':g.name})

        checker = Task(url='/builder', params={'group':'ctrp-taskcheck'})
        taskcheck = Queue(name='taskcheck')
        taskcheck.add(checker)

    return redirect('/rank')
