# -*- coding: utf-8 -*-
#!/usr/bin/env python

from flask import Flask, request, Response
from werkzeug.routing import BaseConverter

import ctrpmodels
import display
import ranker
import rostermgmt

app = Flask(__name__)
app.debug = True

class RegexConverter(BaseConverter):
    def __init__(self, url_map, *items):
        super(RegexConverter, self).__init__(url_map)
        self.regex = items[0]

app.url_map.converters['regex'] = RegexConverter
app.jinja_env.filters['normalize'] = display.normalize

@app.route('/')
def root():
    return display.display()

@app.route('/history')
def history():
    return display.display_history(request)

@app.route('/loadgroups')
def load_groups():
    return rostermgmt.load_groups()

@app.route('/rank', methods=['GET', 'POST'])
def rank():
    if request.method == 'GET':
        return ranker.rank()
    return ranker.start_ranking()

# This is used by the cron job to start ranking automatically. We call the ranker
# but we don't care about the redirect that it responds with. Instead just return
# a 200 so the cron job doesn't fail.
@app.route('/startrank')
def startrank():
    ranker.start_ranking()
    return '', 200

@app.route('/builder', methods=['POST'])
def builder():
    return ranker.run_builder(request)

@app.route('/migrate')
def migrate():
    return ctrpmodels.migrate()

@app.route('/<regex("tier(\d+)"):tier>')
def display_tier(tier):
    return display.display_tier(tier)

@app.route('/tooltips.js')
def tooltips():
    return Response(display.build_tooltips(), content_type='application/javascript')

@app.route('/loadone')
def load_one():
    return ranker.loadone(request)
