# -*- coding: utf-8 -*-
"""
Extensions
"""

import re
import six
import logging
import inspect
import functools
import itsdangerous
import arrow
import copy
import blinker
from flask import (request, current_app, send_file, session)
import flask_cloudy
import flask_recaptcha
import flask_caching
from passlib.hash import bcrypt as passhash
from . import (Flasik,
               extends,
               utils,
               g,
               get_config)

__all__ = ["cache",
           "storage",
           "upload_file",
           "delete_file",
           "download_file",
           "get_file",
           "recaptcha",
           "bcrypt",
           "send_mail",
           "paginate",
           "_",
           ]

@extends
def setup(app):
    app.jinja_env.filters.update({
        "format_datetime": format_datetime
    })

    check_config_keys = [
        "SECRET_KEY",
        "ADMIN_EMAIL",
        "CONTACT_EMAIL",
        "MAIL_URL",
        "MAIL_SENDER",
        "DB_URL",
        "DATETIME_TIMEZONE",
        "DATETIME_FORMAT",
        "RECAPTCHA_SITE_KEY",
        "RECAPTCHA_SECRET_KEY"
    ]
    for k in check_config_keys:
        if k not in app.config \
                or not app.config.get(k):
            msg = "Missing config key value: %s " % k
            logging.warning(msg)


def set_flash_data(data):
    """
    Set temporary data in the session. 
    It will replace the previous one
    :param data:
    :return:
    """
    session["_flash_data"] = data

def get_flashed_data():
    """
    Retrieve and pop data from the session
    :return: mixed
    """
    return session.pop("_flash_data", None)

def utc_now():
    """
    Return the utcnow arrow object
    :return: Arrow
    """
    return arrow.utcnow()


def format_datetime(utcdatetime, format=None, timezone=None):
    """
    Return local datetime based on the timezone
    It will automatically format the date. 
    To not format the date, set format=False
    
    :param utcdatetime: Arrow or string
    :param format: string of format or False
    :param timezone: string, ie: US/Eastern
    :return:
    """
    if utcdatetime is None:
        return None

    timezone = timezone or get_config("DATETIME_TIMEZONE", "US/Eastern")
    dt = utcdatetime.to(timezone) \
        if isinstance(utcdatetime, arrow.Arrow) \
        else arrow.get(utcdatetime, timezone)
    if format is False:
        return dt

    _ = get_config("DATETIME_FORMAT")
    format = _.get("default") or "MM/DD/YYYY" if not format else _.get(format)
    return dt.format(format)


def send_mail(template, to, **kwargs):
    """
    Alias to mail.send(), but makes template required
    ie: send_mail("welcome-to-the-site.txt", "user@email.com")
    :param template: 
    :param to:
    :param kwargs:
    :return:
    """

    def cb():
        return flasik.ext.mail.mail.send(to=to, template=template, **kwargs)

    return signals.send_mail(cb, data={"to": to, "template": template, "kwargs": kwargs})


# Cache
cache = flask_caching.Cache()
extends(cache.init_app)

# Storage
storage = flask_cloudy.Storage()
extends(storage.init_app)

# Upload file
def upload_file(_props_key, file, **kw):
    """
    Wrapper around storage.upload to upload a file conveniently by using set 
    properties, so no need to keep rewriting the same code.
    config file must have STORAGE_UPLOAD_FILE_PROPS where it contains k/v, ie:

    STORAGE_UPLOAD_FILE_PROPS = {
        "profile-image": {
            "extensions": ["jpg", "jpeg", "gif", "png"],
            "prefix": "/profile-image/",
            "public": True
        }, 
        ...
    }

    upload_file("profile-image", my_file)
    :param _props_key: (str) a key available in config.STORAGE_UPLOAD_FILE_PROPS
    :param file: FileStorage object or string location
    :param kw: extra **kw for 
    :return: Storage object
    """
    kwargs = {}
    if _props_key is not None:
        conf = get_config("STORAGE_UPLOAD_FILE_PROPS")
        if not conf:
            raise ValueError("Missing STORAGE_UPLOAD_FILE_PROPS in config")
        if _props_key not in conf:
            raise ValueError("Missing '%s' in config STORAGE_UPLOAD_FILE_PROPS" % _props_key)
        kwargs.update(conf.get(_props_key))
    kwargs.update(kw)

    return signals.upload_file(lambda: storage.upload(file, **kwargs))

# Get file
def get_file(object_name):
    """
    Alias to get file from storage 
    :param object_name: 
    :return: Storage object
    """
    return storage.get(object_name)

# Delete file
def delete_file(fileobj):
    """
    Alias to delete a file from storage
    :param fileobj: 
    :return: 
    """
    if not isinstance(fileobj, (flask_cloudy.Object, flasik_db.StorageObject)):
        raise TypeError("Invalid file type. Must be of flask_cloudy.Object")
    return signals.delete_file(lambda: fileobj.delete())

# Download file
def download_file(filename, object_name=None, content=None, as_attachment=True, timeout=60):
    """
    Alias to download a file object as attachment, or convert some text as . 
    :param filename: the filename with extension.
        If the file to download is an StorageOject, filename doesn't need to have an extension. 
            It will automatically put it
        If the file to download is a `content` text, extension is required.
    :param object_name: the file storage object name
    :param content: string/bytes of text
    :param as_attachment: to download as attachment
    :param timeout: the timeout to download file from the cloud
    :return: 
    """
    if object_name:
        file = get_file(object_name)
        if not isinstance(file, (flask_cloudy.Object, flasik_db.StorageObject)):
            raise TypeError("Can't download file. It must be of StorageObject type")
        return file.download_url(timeout=timeout, name=filename)
    elif content:
        buff = six.BytesIO()
        buff.write(content)
        buff.seek(0)
        return send_file(buff,
                         attachment_filename=filename,
                         as_attachment=as_attachment)
    raise TypeError("`file` object or `content` text must be provided")

# Recaptcha
recaptcha = flask_recaptcha.ReCaptcha()
extends(recaptcha.init_app)

# ------------------------------------------------------------------------------

"""
# Signals
:decorator

Signals allow you to connect to a function and re

Usage

1.  Emitter.
    Decorate your function with @emit_signal.
    That function itself will turn into a decorator that you can use to
    receivers to be dispatched pre and post execution of the function

    @emit_signal()
    def login(*a, **kw):
        # Run the function
        return

    @emit_signal()
    def logout(your_fn_args)
        # run function
        return

2.  Receivers/Observer.
    The function that was emitted now become signal decorator to use on function
    that will dispatch pre and post action. The pre and post function will
    be executed before and after the signal function runs respectively.

    @login.pre.connect
    def my_pre_login(*a, **kw):
        # *a, **kw are the same arguments passed to the function
        print("This will run before the signal is executed")

    @login.post.connect
    def my_post_login(result, **kw):
        result: the result back
        **kw
            params: params passed 
            sender: the name of the funciton
            emitter: the function that emits this signal
            name: the name of the signal
        print("This will run after the signal is executed")

    # or for convenience, same as `post.connect`, but using `observe`
    @login.observe
    def my_other_post_login(result, **kw):
        pass
    
3.  Send Signal
    Now sending a signal is a matter of running the function.

    ie:
    login(username, password)

That's it!
"""
__signals_namespace = blinker.Namespace()

def emit_signal(sender=None, namespace=None):
    """
    @emit_signal
    A decorator to mark a method or function as a signal emitter
    It will turn the function into a decorator that can be used to 
    receive signal with: $fn_name.pre.connect, $fn_name.post.connect 
    *pre will execute before running the function
    *post will run after running the function
    
    **observe is an alias to post.connect
    
    :param sender: string  to be the sender.
    If empty, it will use the function __module__+__fn_name,
    or method __module__+__class_name__+__fn_name__
    :param namespace: The namespace. If None, it will use the global namespace
    :return:

    """
    if not namespace:
        namespace = __signals_namespace

    def decorator(fn):
        fname = sender
        if not fname:
            fnargs = inspect.getargspec(fn).args
            fname = fn.__module__
            if 'self' in fnargs or 'cls' in fnargs:
                caller = inspect.currentframe().f_back
                fname += "_" + caller.f_code.co_name
            fname += "__" + fn.__name__

        # pre and post
        fn.pre = namespace.signal('pre_%s' % fname)
        fn.post = namespace.signal('post_%s' % fname)
        # alias to post.connect
        fn.observe = fn.post.connect

        def send(action, *a, **kw):
            sig_name = "%s_%s" % (action, fname)
            result = kw.pop("result", None)
            kw.update(inspect.getcallargs(fn, *a, **kw))
            sendkw = {
                "kwargs": {k: v for k, v in kw.items() if k in kw.keys()},
                "sender": fn.__name__,
                "emitter": kw.get('self', kw.get('cls', fn))
            }
            if action == 'post':
                namespace.signal(sig_name).send(result, **sendkw)
            else:
                namespace.signal(sig_name).send(**sendkw)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            send('pre', *args, **kwargs)
            result = fn(*args, **kwargs)
            kwargs["result"] = result
            send('post', *args, **kwargs)
            return result
        return wrapper
    return decorator



# ----

def sign_jwt(data, secret_key, expires_in, salt=None, **kw):
    """
    To create a signed JWT
    :param data:
    :param secret_key:
    :param expires_in:
    :param salt:
    :param kw:
    :return: string
    """
    s = itsdangerous.TimedJSONWebSignatureSerializer(secret_key=secret_key,
                                                     expires_in=expires_in,
                                                     salt=salt,
                                                      **kw)
    return s.dumps(data)


def unsign_jwt(token, secret_key, salt=None, **kw):
    """
    To unsign a JWT token
    :param token:
    :param kw:
    :return: mixed data
    """
    s = itsdangerous.TimedJSONWebSignatureSerializer(secret_key, salt=salt, **kw)
    return s.loads(token)


class TimestampSigner2(itsdangerous.TimestampSigner):
    expires_in = 0

    def get_timestamp(self):
        now = datetime.datetime.utcnow()
        expires_in = now + datetime.timedelta(seconds=self.expires_in)
        return int(expires_in.strftime("%s"))

    @staticmethod
    def timestamp_to_datetime(ts):
        return datetime.datetime.fromtimestamp(ts)


class URLSafeTimedSerializer2(itsdangerous.URLSafeTimedSerializer):
    default_signer = TimestampSigner2

    def __init__(self, secret_key, expires_in=3600, salt=None, **kwargs):
        self.default_signer.expires_in = expires_in
        super(self.__class__, self).__init__(secret_key, salt=salt, **kwargs)


def sign_url_safe(data, secret_key, expires_in=None, salt=None, **kw):
    """
    To sign url safe data.
    If expires_in is provided it will Time the signature
    :param data: (mixed) the data to sign
    :param secret_key: (string) the secret key
    :param expires_in: (int) in minutes. Time to expire
    :param salt: (string) a namespace key
    :param kw: kwargs for itsdangerous.URLSafeSerializer
    :return:
    """
    if expires_in:
        expires_in *= 60
        s = URLSafeTimedSerializer2(secret_key=secret_key,
                                    expires_in=expires_in,
                                    salt=salt,
                                    **kw)
    else:
        s = itsdangerous.URLSafeSerializer(secret_key=secret_key,
                                           salt=salt,
                                           **kw)
    return s.dumps(data)


def unsign_url_safe(token, secret_key, salt=None, **kw):
    """
    To sign url safe data.
    If expires_in is provided it will Time the signature
    :param token:
    :param secret_key:
    :param salt: (string) a namespace key
    :param kw:
    :return:
    """
    if len(token.split(".")) == 3:
        s = URLSafeTimedSerializer2(secret_key=secret_key, salt=salt, **kw)
        value, timestamp = s.loads(token, max_age=None, return_timestamp=True)
        now = datetime.datetime.utcnow()
        if timestamp > now:
            return value
        else:
            raise itsdangerous.SignatureExpired(
                'Signature age %s < %s ' % (timestamp, now),
                payload=value,
                date_signed=timestamp)
    else:
        s = itsdangerous.URLSafeSerializer(secret_key=secret_key, salt=salt, **kw)
        return s.loads(token)


def sign_data(data, secret_key, expires_in=None, salt=None, **kw):
    if expires_in:
        pass
    else:
        s = itsdangerous.Serializer(secret_key=secret_key, salt=salt, **kw)
        return s.dumps(data)


def unsign_data(data, secret_key, salt=None, **kw):
    s = itsdangerous.Serializer(secret_key=secret_key, salt=salt, **kw)
    return s.loads(data)

# ------------------------------------------------------------------------------

