# -*- coding: utf-8 -*-
#!/usr/bin/env python

import datetime
from flask import render_template, redirect
import ctrpmodels

def display(dcl):
    # TODO: do i bother to keep this?
    last_updated = None
    if last_updated is None:
        last_updated = datetime.datetime.now()

    template_values = {
        'last_updated': last_updated,
        'title' : 'Main',
        'tier': 24
    }
    response = render_template('header.html', **template_values)

    raid_map = {}
    for raid in ctrpmodels.Constants.raids:
        raid_map[raid.get('slug', '')] = raid.get('name', '');

    groups = query_groups(dcl)
    for group in groups:
        template_values = {'group' : group}
        response += render_template('group-raid-header.html', **template_values)
        for k,v in group.get('raids').items():

            raid_name = raid_map.get(k, 'Unknown Raid {}'.format(k))
            boss_count = len(v.get('Normal', []))

            template_values = {
                'name': raid_name,
                'boss_count': boss_count,
                'normal_kills': boss_count - v.get('Normal', []).count(None),
                'heroic_kills': boss_count - v.get('Heroic', []).count(None),
                'mythic_kills': boss_count - v.get('Mythic', []).count(None)
            }
            response += render_template('group-raid-raid.html', **template_values)
        response += render_template('group-raid-footer.html')

    response += render_template('footer.html')
    return response, 200

def build_tooltips(dcl):
    return

    response = ('$(function() {\n'
                '  $(document).tooltip({\n'
                '    items: "[ttid]",\n'
                '    content: function() {\n'
                '      var tooltips = {};\n')

    groups = query_groups(dcl)

    for raidinfo in ctrpmodels.Constants.raids:
        raid = raidinfo[0]
        for group in groups:
            normaltext = ""
            heroictext = ""
            mythictext = ""
            bosses = []
            groupraid = getattr(group, raid)
            raidbosses = getattr(ctrpmodels.Constants, raid+'bosses')

            for boss in groupraid.bosses:
                bosses.append((boss.name, boss.normaldead, boss.heroicdead, boss.mythicdead))
            index_dict = {item: index for index, item in enumerate(raidbosses)}
            bosses.sort(key=lambda t: index_dict[t[0]])

            for boss in bosses:
                if boss[1] != None:
                    normaltext += "<div class='bossdead'>%s</div>" % boss[0]
                else:
                    normaltext += "<div class='bossalive'>%s</div>" % boss[0]
                if boss[2] != None:
                    heroictext += "<div class='bossdead'>%s</div>" % boss[0]
                else:
                    heroictext += "<div class='bossalive'>%s</div>" % boss[0]
                if boss[3] != None:
                    mythictext += "<div class='bossdead'>%s</div>" % boss[0]
                else:
                    mythictext += "<div class='bossalive'>%s</div>" % boss[0]

            template_values = {
                'name': group.name,
                'raid': raid,
                'normaltext': normaltext,
                'heroictext': heroictext,
                'mythictext': mythictext,
            }

            response += render_template('group-tooltip.js', **template_values)

    response += ('\n'
                 '      var element = $(this);\n'
                 '      var ttid = element.attr("ttid");\n'
                 '      return tooltips[ttid];\n'
                 '    }});\n'
                 '});')

    return response

def display_history(dcl):

    # TODO: do i bother to keep this?
    last_updated = None
    if last_updated is None:
        last_updated = datetime.datetime.now()

    template_values = {
        'last_updated': last_updated,
        'title' : 'History'
    }
    response = render_template('header.html', **template_values)

    # add the beginnings of the table
    response += '<table style="margin-left:50px;margin-right:50px">\n'

    # request all of the history entries, sorted in reverse order by date
    curdate = datetime.datetime.now()
    curdate = datetime.datetime(curdate.year, curdate.month, curdate.day)
    oneday = datetime.timedelta(days=1)

    raid_names = {}
    for raid in ctrpmodels.Constants.raids:
        raid_names[raid.get('slug', '')] = raid.get('name', '')

    for i in range(0, 13):
        response += '<tr><td colspan="2" class="history-date">%s</td></tr>\n' % curdate.date()

        # Retrieve all of the entires for this date ordered by group name
        query = dcl.query(kind='History',
                          filters=[('date','>=',curdate),('date','<=',curdate+oneday)])
        updates = None
        if query:
            updates = query.fetch()

        update_count = 0
        if updates:

            for update in updates:
                update_count += 1

                template_values = { 'group': update.get('group', '') }
                response += render_template('history-header.html', **template_values)

                kills = update.get('kills', {})
                for slug in kills.keys():
                    raid_data = kills.get(slug, {})

                    for diff in ctrpmodels.Constants.difficulties:
                        diff_data = raid_data.get(diff, {})
                        if diff_data:
                            template_values = {
                                'name': raid_names.get(slug, ''),
                                'diff': diff,
                                'kills': diff_data.get('kills', []),
                                'total': diff_data.get('total', 0),
                                'bosses': raid_data.get('boss_count', 0)
                            }
                            response += render_template('history-entry.html', **template_values)

                response += '\n</td>\n</tr>\n'

        if not update_count:

            # if there were no results for this date, add just a simple
            # entry displaying nothing
            response += '<tr>'
            response += '<td colspan="2" style="text-align:center">'
            if i == 0:
                current = datetime.datetime.now()
                if current > last_updated:
                    response += 'Data not parsed for today yet'
                else:
                    response += 'No new kills for this date!'
            else:
                response += 'No new kills for this date!'
            response += '</td>'
            response += '</tr>\n'

        curdate -= oneday

    response += '</table>\n'
    response += render_template('footer.html')

    return response, 200

def display_tier(tier):

    tier_number = tier[-2:]
    template_values = {
        'title' : 'Tier %s' % tier_number,
        'tier': tier_number
    }

    response = render_template('header.html', **template_values)
    response += render_template('%s.html' % tier)
    response += render_template('footer.html')
    return response, 200

def query_groups(dcl, groupname=None):

    query = dcl.query(kind='Group')
    return sorted(query.fetch(), key=lambda x: ctrpmodels.get_sort_key(x), reverse=True)
