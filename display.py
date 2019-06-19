# -*- coding: utf-8 -*-
#!/usr/bin/env python

import datetime
from flask import render_template, redirect
import ctrpmodels

def normalize(groupname):
    return groupname.lower().replace('\'', '').replace(' ', '-').replace('"', '')

def display():
    last_updated = ctrpmodels.Global.get_last_updated()
    if last_updated is None:
        last_updated = datetime.datetime.now()

    template_values = {
        'last_updated': last_updated,
        'title' : 'Main',
        'tier': 24
    }
    response = render_template('header.html', **template_values)
    response += '<table>\n'

    groups = ctrpmodels.Group.query_for_singletier_display()
    for group in groups:
        template_values = {'group' : group}
        response += render_template('group-raids.html', **template_values)

    response += '</table>\n'
    response += render_template('footer.html')
    return response, 200

def build_tooltips():

    response = ('$(function() {\n'
                '  $(document).tooltip({\n'
                '    items: "[ttid]",\n'
                '    content: function() {\n'
                '      var tooltips = {};\n')

    groups = ctrpmodels.Group.query_for_singletier_display()
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

def display_history(request):
    group = request.form.get('group', '')
    if group:
        return display_group_history(group)

    return display_full_history()

def display_full_history():
    last_updated = ctrpmodels.Global.get_last_updated()
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
    curdate = datetime.date.today()
    oneday = datetime.timedelta(1)

    for i in xrange(0, 13):
        response += '<tr><td colspan="2" class="history-date">%s</td></tr>\n' % curdate

        # Retrieve all of the entires for this date ordered by group name
        updates = ctrpmodels.History.get_for_date(curdate)
        if not updates:
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

        else:

            # now loop through the groups and output the updates in some
            # fashion
            for update in updates:

                template_values = {
                    'history': update,
                    'num_aep_bosses': len(ctrpmodels.Constants.aepbosses)
                }
                response += render_template('history.html', **template_values)
                response += '\n'

        curdate -= oneday

    response += '</table>\n'
    response += render_template('footer.html')

    return response, 200

def display_group_history(group_name):
    last_updated = ctrpmodels.Global.get_last_updated()
    if last_updated is None:
        last_updated = datetime.datetime.now()

    template_values = {
        'last_updated': last_updated,
        'title' : 'History'
    }
    response = render_template('header.html', **template_values)

    # Record all history for this group that has been recorded sorted by the
    # date
    entries = ctrpmodels.History.get_for_group(group_name)

    if not entries:
        response += 'No history recorded for group %s' % group_name
    else:
        response += '<div class="history-date">%s</div><p/>' % group_name
        response += '<table style="margin-left:50px;11margin-right:50px">\n'

        for entry in entries:
            template_values = {
                'history': entry,
                'num_aep_bosses': len(ctrpmodels.Constants.aepbosses)
            }
            response += render_template('group-history.html', **template_values)
            response += '\n'

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
