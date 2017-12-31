#!/usr/bin/python
# encoding: utf-8

import os
import re
import glob
import json
import uuid
import yaml
import urllib
import logging
import datetime

from beaker.middleware import SessionMiddleware
from cork import Cork

import bottle
import bottle.ext.sqlite
from bottle import get, post, route, hook, request, redirect, run, view
from bottle import static_file, template, SimpleTemplate
from bottle_utils.i18n import I18NPlugin, i18n_path, i18n_url, lazy_gettext as _

SESSION = {
    'session.type': 'cookie',
    'session.cookie_expires': 60 * 60 * 24 * 365,
    'session.encrypt_key': "o(eaji3jgoijeh83",
    'session.validate_key': True,
}

app = bottle.default_app()
config = yaml.load(open("config.yaml"))
sqlite = bottle.ext.sqlite.Plugin(dbfile='dugnad.db')
app.install(sqlite)
app = I18NPlugin(app, config['languages'], config['languages'][0][0], "lang")
app = SessionMiddleware(app, SESSION)

logging.basicConfig(level=logging.INFO)

cork = Cork('auth', email_sender=config['email'])
authorize = cork.make_auth_decorator(fail_redirect="/login", role="dugnadsfolk")

from dugnad.util import dzi

class Form:
    class Button:
        def __init__(self, blueprint):
            self.name = blueprint['name']

        def tohtml(self):
            s = "<button id='%s' name='%s'>%s</button>" % (
                    self.name, self.name, _(self.name))
            return s

    class Input:
        def __init__(self, blueprint):
            self.type = blueprint['type']
            self.name = blueprint['name']
            self.size = blueprint.get('size', "24")
            self.readonly = blueprint.get('disabled')
            self.url = blueprint.get('url')
            self.path = blueprint.get('path')
            self.value = ""

        def tohtml(self, label=True):
            s = ""
            if label and self.type != "hidden":
                s += "<label>%s</label>\n" % _(self.name)
            s += "<input type=%s name='%s'" % (self.type, self.name)
            s += " size='%s'" % self.size
            s += " id='%s'" % self.name
            if self.value:
                s += " value='%s'" % self.value
            if self.url:
                s += " data-url='%s'" % self.url
            if self.path:
                s += " data-url='%s'" % path(self.path)
            if self.readonly:
                s += " readonly"
            s += ">"
            return s

    class Textfield:
        def __init__(self, blueprint):
            self.name = blueprint['name']
            self.readonly = blueprint.get('disabled')
            self.value = ""

        def tohtml(self):
            s = ""
            s += "<label>%s</label>\n" % _(self.name)
            s += "<textarea name='%s'" % self.name
            if self.readonly:
                s += " readonly"
            s += ">%s</textarea>" % self.value or ""
            return s

    def __init__(self, slug, recipe):
        self.slug = slug
        self.inputs = []
        for blueprint in recipe:
            for element in self.build(blueprint):
                self.inputs.append(element)

    def build(self, blueprint):
        if blueprint['type'] == "textfield":
            return [self.Textfield(blueprint)]
        elif blueprint['type'] == "annotation":
            return [self.Input({'type': 'text',
                                'name': 'marked-pages',
                                'disabled': True
                               }),
                    self.Input({'type': 'hidden', 'name': blueprint['name']}),
                    self.Button({'name': 'mark-page'})
                   ]
        else:
            return [self.Input(blueprint)]

    def tohtml(self):
        h = ""
        for element in self.inputs: h += "<p>" + element.tohtml()
        return h

    def validate(self, request):
        for element in self.inputs:
            if element.name in request:
                element.value = request[element.name]

class Changelog:
    fmt = r"(?P<date>.+):\s*(?P<text>.*)\s*\((?P<project>.*)\)"

    def __init__(self, path):
        self.changes = []
        with open(path, "r") as changefile:
            for line in list(changefile):
                match = re.match(self.fmt, line)
                if match: self.changes.append(match.groupdict())

class Post:
    @classmethod
    def find(cls, db, uuid):
        query = "select * from transcriptions where id = ?"
        row = db.execute(query, [uuid]).fetchone()
        return cls(dict(row))

    def __init__(self, attrs, proj=None):
        for k in attrs:
            setattr(self, k, attrs[k])
        if proj:
            self.project = proj
        else:
            self.project = Project.find(self.project)
        self.annotation = json.loads(self.annotation)

    def path(self):
        return path("/projects/%s/%s" % (self.project.slug, self.id))

    def update(self, db, uid, data):
        # finished = not data.get('later')
        query = "delete from markings where post = ?"
        db.execute(query, [self.id])
        if 'annotation' in data:
            pages = json.loads(data['annotation'])
            for page, marks in pages.iteritems():
                self.project.addmarkings(db, self.id, uid, page, marks)
        now = str(datetime.datetime.now())
        query = "update transcriptions set annotation = ?, updated = ? where id = ?"
        db.execute(query, [json.dumps(dict(data)), now, self.id])

    def wkt(self):
        if self.annotation.get('footprintWKT'):
            return json.dumps(self.annotation['footprintWKT'])

class Project:
    @classmethod
    def find(cls, slug):
        path = "projects/%s.yaml" % slug
        return cls(path)

    def __init__(self, path):
        self.slug = os.path.splitext(os.path.basename(path))[0]
        self.hidden = False
        self.finished = False
        attrs = yaml.load(open(path, 'r'))
        for k in attrs:
            setattr(self, k, attrs[k])

    def userlog(self, db, uid):
        query = "select * from transcriptions where project = ? and user = ? order by updated desc"
        rows = db.execute(query, [self.slug, uid]).fetchall()
        return [Post(dict(row), self) for row in rows]

    def contribute(self, db, uid, data):
        finished = not data.get('later')
        postid = str(uuid.uuid4())
        if 'annotation' in data:
            pages = json.loads(data['annotation'])
            for page, marks in pages.iteritems():
                self.addmarkings(db, postid, uid, page, marks)
        now = str(datetime.datetime.now())
        query = "insert into transcriptions values(?, ?, ?, ?, ?, ?, ?, ?)"
        # id, key, user, project, date, annotation, finished, updated
        db.execute(query, [postid, "", uid, self.slug, now,
                json.dumps(dict(data)), finished, now])

    def addmarkings(self, db, postid, uid, page, data):
        # id, post, project, page, markings, user, date
        now = str(datetime.datetime.now())
        query = "insert into markings values(?, ?, ?, ?, ?, ?, ?)"
        db.execute(query, [str(uuid.uuid4()), postid, self.slug, page,
                   json.dumps(data), uid, now])

def dropcrumb(text, url=None):
    request.crumbs.append((url, text))

def path(raw):
    return i18n_path(raw)

def url(*args, **kw):
    return i18n_url(*args, **kw)

def query(raw, limitto=None):
    if limitto:
        params = {}
        for k, v in raw.iteritems():
            if k in limitto: params[k] = v
    else:
        params = raw
    return "?" + urllib.urlencode(params)

SimpleTemplate.defaults["request"] = request
SimpleTemplate.defaults["config"] = config
SimpleTemplate.defaults["crumb"] = dropcrumb
SimpleTemplate.defaults["path"] = path
SimpleTemplate.defaults["url"] = url

@hook('before_request')
def before_request():
    request.crumbs = []
    if cork.user_is_anonymous:
        request.user = None
    else:
        request.user = cork.current_user
        request.uid = cork.current_user.username

@get('/')
@view('index')
def index():
    changelog = Changelog('changelog')
    projects = []
    projects = [Project(f) for f in glob.glob("projects/*.yaml")]
    return { 'changelog': changelog, 'projects': projects }

@get('/changelog')
@view('changelog')
def changelog():
    changelog = Changelog('changelog')
    return { 'changelog': changelog }

@get('/project/<slug>/overview')
@view('overview')
def overview(slug):
    project = Project.find(slug)
    return { 'project': project }

@get('/project/<slug>/markings/<page>')
def markings(slug, page, db):
    query = "select * from markings where project = ? and page = ?"
    rows = db.execute(query, [slug, page])
    results = [dict(r) for r in rows]
    return json.dumps(results)

@get('/project/<slug>/<uuid>/markings/<page>')
def markings_post(slug, page, db):
    query = "select * from markings where id = ? and page = ?"
    rows = db.execute(query, [slug, page])
    results = [dict(r) for r in rows]
    return json.dumps(results)

@get('/project/<slug>')
def project(slug):
    def document(project):
        forms = [Form(form, project.forms[form]) for form in project.order]
        [form.validate(request.query) for form in forms]
        return template("document", { 'project': project, 'forms': forms })
    
    def transcribe(project):
        pass

    project = Project.find(slug)
    dispatch = {
        'document': document,
        'transcription': transcribe
    }
    return dispatch[project.type](project)

@post('/project/<slug>')
def transcribe(slug, db):
    project = Project.find(slug)
    base = request.headers['referer'].split("?")[0]
    if 'skip' in request.forms: redirect(base)
    project.contribute(db, request.user.username, request.forms)
    redirect(base + query(request.forms, project.sticky))

@get('/project/<slug>/userlog')
def userlog(slug, db):
    cork.require(role='dugnadsfolk', fail_redirect='/')
    project = Project.find(slug)
    posts = project.userlog(db, request.user.username)
    if request.query.view == "map":
        return template("map", { 'project': project, 'posts': posts })
    elif request.query.view == "browse":
        return template("browse", { 'project': project, 'posts': posts })
    return template("list", { 'project': project, 'posts': posts })

@get('/project/<slug>/<uuid>')
def review(slug, uuid, db):
    cork.require(role='dugnadsfolk', fail_redirect='/')
    project = Project.find(slug)
    post = Post.find(db, uuid)
    forms = [Form(form, project.forms[form]) for form in project.order]
    [form.validate(post.annotation) for form in forms]
    return template("document",{'id': uuid, 'project': project, 'forms': forms})

@post('/project/<slug>/<uuid>')
def revise(slug, uuid, db):
    cork.require(role='dugnadsfolk', fail_redirect='/')
    post = Post.find(db, uuid)
    post.update(db, request.user.username, request.forms)
    redirect(path('/project/%s/userlog' % slug))

@get('/lookup/<key>')
def lookup(key, db):
    q = request.query.q
    if key in config['lookup'] and q:
        src = config['lookup'][key]
        query = "select * from %s where %s like ? limit 25" % (
                src['table'], src['key'])
        rows = db.execute(query, ["%" + q + "%"]).fetchall()
        results = [dict(r) for r in rows]
        return json.dumps(results)

@get('/static/<path:path>')
def static(path):
    return static_file(path, root='static')

# authentication
@get('/login')
@view('login')
def login():
    fail = 'fail' in request.query
    validated = 'validated' in request.query
    return {'fail': fail, 'validated': validated}

@post('/login')
def login():
    login = request.POST.get("name")
    passw = request.POST.get("password")
    cork.login(login, passw, success_redirect="/", fail_redirect="/login?fail")

@route('/logout')
def logout():
    cork.logout(success_redirect='/login')

@post('/register')
def register():
    login = request.POST.get("name")
    passw = request.POST.get("password")
    email = request.POST.get("email")
    cork.register(login, passw, email, role='dugnadsfolk')
    return template("check-mail")

@route('/validate/<code>', name='validate')
def validate(code):
    cork.validate_registration(code)
    redirect(path("/login?validated"))

@post('/reset')
def resetpassword():
    login = request.POST.get("name")
    email = request.POST.get("email")
    cork.send_password_reset_email(username=login, email_addr=email)
    return template("reset-mail")

@get('/password/:reset_code')
@view('password')
def setpassword(code):
    return dict(code=code)

run(app, host='localhost', port=8080, debug=True)
