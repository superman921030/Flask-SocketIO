import os
import sys

import eventlet
import socketio
import flask
from werkzeug.debug import DebuggedApplication
from werkzeug.serving import run_with_reloader
from werkzeug._internal import _log

#from test_client import SocketIOTestClient


class SocketIO(object):
    """Create a Flask-SocketIO server.

    :param app: The flask application instance. If the application instance
                isn't known at the time this class is instantiated, then call
                ``socketio.init_app(app)`` once the application instance is
                available.
    """

    def __init__(self, app=None, **kwargs):
        self.app = None
        self.server = None
        self.exception_handlers = {}
        self.default_exception_handler = None
        if app is not None:
            self.init_app(app, **kwargs)

    def init_app(self, app, **kwargs):
        if self.app is not None and self.app != app:
            raise RuntimeError('Cannot associate a SocketIO instance with '
                               'more than one application')
        if not hasattr(app, 'extensions'):
            app.extensions = {}
        app.extensions['socketio'] = self
        self.server = socketio.Server(**kwargs)
        self.app = app

    def _on_message(self, message, handler, namespace='/'):
        self.server.on(message, handler, namespace=namespace)

    def on(self, message, namespace=None):
        """Decorator to register a SocketIO event handler.

        This decorator must be applied to SocketIO event handlers. Example::

            @socketio.on('my event', namespace='/chat')
            def handle_my_custom_event(json):
                print('received json: ' + str(json))

        :param message: The name of the event. Use ``'message'`` to define a
                        handler that takes a string payload, ``'json'`` to
                        define a handler that takes a JSON blob payload,
                        ``'connect'`` or ``'disconnect'`` to create handlers
                        for connection and disconnection events, or else, use a
                        custom event name, and use a JSON blob as payload.
        :param namespace: The namespace on which the handler is to be
                          registered. Defaults to the global namespace.
        """
        namespace = namespace or '/'

        if namespace in self.exception_handlers or \
                self.default_exception_handler is not None:
            def decorator(handler):
                def _handler(sid, *args):
                    with self.app.request_context(self.server.environ[sid]):
                        if 'saved_session' in self.server.environ[sid]:
                            self._copy_session(self.server.environ[sid]['saved_session'], flask.session)
                        flask.request.sid = sid
                        flask.request.namespace = namespace
                        try:
                            ret = handler(*args)
                        except:
                            err_handler = self.exception_handlers.get(
                                namespace, self.default_exception_handler)
                            type, value, traceback = sys.exc_info()
                            return err_handler(value)
                        self.server.environ[sid]['saved_session'] = {}
                        self._copy_session(flask.session, self.server.environ[sid]['saved_session'])
                        return ret
                self.server.on(message, _handler, namespace=namespace)
            return decorator
        else:
            def decorator(handler):
                def _handler(sid, *args):
                    with self.app.request_context(self.server.environ[sid]):
                        if 'saved_session' in self.server.environ[sid]:
                            self._copy_session(self.server.environ[sid]['saved_session'], flask.session)
                        flask.request.sid = sid
                        flask.request.namespace = namespace
                        ret = handler(*args)
                        self.server.environ[sid]['saved_session'] = {}
                        self._copy_session(flask.session, self.server.environ[sid]['saved_session'])
                        return ret
                self.server.on(message, _handler, namespace=namespace)
            return decorator

    def on_error(self, namespace=''):
        """Decorator to define a custom error handler for SocketIO events.

        This decorator can be applied to a function that acts as an error
        handler for a namespace. This handler will be invoked when a SocketIO
        event handler raises an exception. The handler function must accept one
        argument, which is the exception raised. Example::

            @socketio.on_error(namespace='/chat')
            def chat_error_handler(e):
                print('An error has occurred: ' + str(e))

        :param namespace: The namespace for which to register the error
                          handler. Defaults to the global namespace.
        """
        def decorator(exception_handler):
            if not callable(exception_handler):
                raise ValueError('exception_handler must be callable')
            self.exception_handlers[namespace] = exception_handler
        return decorator

    def on_error_default(self, exception_handler):
        """Decorator to define a default error handler for SocketIO events.

        This decorator can be applied to a function that acts as a default
        error handler for any namespaces that do not have a specific handler.
        Example::

            @socketio.on_error_default
            def error_handler(e):
                print('An error has occurred: ' + str(e))
        """
        if not callable(exception_handler):
            raise ValueError('exception_handler must be callable')
        self.default_exception_handler = exception_handler

    def emit(self, event, *args, **kwargs):
        """Emit a server generated SocketIO event.

        This function emits a user-specific SocketIO event to one or more
        connected clients. A JSON blob can be attached to the event as payload.
        This function can be used outside of a SocketIO event context, so it is
        appropriate to use when the server is the originator of an event, for
        example as a result of a regular HTTP message. Example::

            @app.route('/ping')
            def ping():
                socketio.emit('ping event', {'data': 42}, namespace='/chat')

        :param event: The name of the user event to emit.
        :param args: A dictionary with the JSON data to send as payload.
        :param namespace: The namespace under which the message is to be sent.
                          Defaults to the global namespace.
        :param room: Send the message to all the users in the given room. If
                     this parameter is not included, the event is sent to
                     all connected users.
        """
        # TODO: handle skip_sid
        self.server.emit(event, *args, namespace=kwargs.get('namespace', '/'),
                         room=kwargs.get('room'),
                         callback=kwargs.get('callback'))

    def send(self, data, json=False, namespace=None, room=None):
        """Send a server-generated SocketIO message.

        This function sends a simple SocketIO message to one or more connected
        clients. The message can be a string or a JSON blob. This is a simpler
        version of ``emit()``, which should be preferred. This function can be
        used outside of a SocketIO event context, so it is appropriate to use
        when the server is the originator of an event.

        :param message: The message to send, either a string or a JSON blob.
        :param json: ``True`` if ``message`` is a JSON blob, ``False``
                     otherwise.
        :param namespace: The namespace under which the message is to be sent.
                          Defaults to the global namespace.
        :param room: Send the message only to the users in the given room. If
                     this parameter is not included, the message is sent to
                     all connected users.
        """
        self.server.send(data, namespace=namespace, room=room)

    def close_room(self, room, namespace='/'):
        """Close a room.

        This function removes any users that are in the given room and then
        deletes the room from the server. This function can be used outside
        of a SocketIO event context.

        :param room: The name of the room to close.
        :param namespace: The namespace under which the room exists. Defaults
                          to the global namespace.
        """
        self.server.close_room(room, namespace)

    def run(self, app, host=None, port=None, **kwargs):
        """Run the SocketIO web server.

        :param app: The Flask application instance.
        :param host: The hostname or IP address for the server to listen on.
                     Defaults to 127.0.0.1.
        :param port: The port number for the server to listen on. Defaults to
                     5000.
        :param use_reloader: ``True`` to enable the Flask reloader, ``False``
                             to disable it.
        :param resource: The SocketIO resource name. Defaults to
                         ``'socket.io'``. Leave this as is unless you know what
                         you are doing.
        :param transports: Optional list of transports to allow. List of
                           strings, each string should be one of
                           handler.SocketIOHandler.handler_types.
        :param policy_server: Boolean describing whether or not to use the
                              Flash policy server.  Defaults to ``True``.
        :param policy_listener: A tuple containing (host, port) for the
                                policy server. This is optional and used only
                                if policy server is set to true.  Defaults to
                                0.0.0.0:843.
        :param heartbeat_interval: The timeout for the server, we should
                                   receive a heartbeat from the client within
                                   this interval. This should be less than the
                                   ``heartbeat_timeout``.
        :param heartbeat_timeout: The timeout for the client when it should
                                  send a new heartbeat to the server. This
                                  value is sent to the client after a
                                  successful handshake.
        :param close_timeout: The timeout for the client, when it closes the
                              connection it still X amounts of seconds to do
                              re-open of the connection. This value is sent to
                              the client after a successful handshake.
        :param log_file: The file in which you want the PyWSGI server to write
                         its access log.  If not specified, it is sent to
                         ``stderr`` (with gevent 0.13).
        """
        if host is None:
            host = '127.0.0.1'
        if port is None:
            server_name = app.config['SERVER_NAME']
            if server_name and ':' in server_name:
                port = int(server_name.rsplit(':', 1)[1])
            else:
                port = 5000

        resource = kwargs.pop('resource', 'socket.io')
        # use_reloader = kwargs.pop('use_reloader', app.debug)
        # if use_reloader:
        #     # monkey patching is required by the reloader
        #     from gevent import monkey
        #     monkey.patch_all()
        #
        #     def run_server():
        #         self.server.serve_forever()
        #     if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        #         _log('info', ' * Running on http://%s:%d/' % (host, port))
        #     run_with_reloader(run_server)
        # else:
        #     _log('info', ' * Running on http://%s:%d/' % (host, port))
        #     self.server.serve_forever()
        app = socketio.Middleware(self.server, app, socketio_path=resource)
        eventlet.wsgi.server(eventlet.listen((host, port)), app)

    def test_client(self, app, namespace=None):
        """Return a simple SocketIO client that can be used for unit tests."""
        return SocketIOTestClient(app, self, namespace)

    def _copy_session(self, src, dest):
        for k in src:
            dest[k] = src[k]


def emit(event, *args, **kwargs):
    """Emit a SocketIO event.

    This function emits a user-specific SocketIO event to one or more connected
    clients. A JSON blob can be attached to the event as payload. This is a
    function that can only be called from a SocketIO event handler. Example::

        @socketio.on('my event')
        def handle_my_custom_event(json):
            emit('my response', {'data': 42})

    :param event: The name of the user event to emit.
    :param args: A dictionary with the JSON data to send as payload.
    :param namespace: The namespace under which the message is to be sent.
                      Defaults to the namespace used by the originating event.
                      An empty string can be used to use the global namespace.
    :param callback: Callback function to invoke with the client's
                     acknowledgement.
    :param broadcast: ``True`` to send the message to all connected clients, or
                      ``False`` to only reply to the sender of the originating
                      event.
    :param room: Send the message to all the users in the given room.
    """
    broadcast = kwargs.get('broadcast')
    room = kwargs.get('room')
    namespace = kwargs.get('namespace', flask.request.namespace)
    callback = kwargs.get('callback')
    if room is None and not broadcast:
        room = flask.request.sid

    socketio = flask.current_app.extensions['socketio']
    return socketio.emit(event, *args, namespace=namespace, room=room,
                         callback=callback)


def send(message, **kwargs):
    """Send a SocketIO message.

    This function sends a simple SocketIO message to one or more connected
    clients. The message can be a string or a JSON blob. This is a simpler
    version of ``emit()``, which should be preferred. This is a function that
    can only be called from a SocketIO event handler.

    :param message: The message to send, either a string or a JSON blob.
    :param namespace: The namespace under which the message is to be sent.
                      Defaults to the namespace used by the originating event.
                      An empty string can be used to use the global namespace.
    :param callback: Callback function to invoke with the client's
                     acknowledgement.
    :param broadcast: ``True`` to send the message to all connected clients, or
                      ``False`` to only reply to the sender of the originating
                      event.
    :param room: Send the message to all the users in the given room.
    """
    namespace = kwargs.get('namespace', flask.request.namespace)
    callback = kwargs.get('callback')
    broadcast = kwargs.get('broadcast')
    room = kwargs.get('room')
    if room is None and not broadcast:
        room = flask.request.sid

    socketio = flask.current_app.extensions['socketio']
    return socketio.send(message, namespace=namespace, room=room,
                         callback=callback)


def join_room(room):
    """Join a room.

    This function puts the user in a room, under the current namespace. The
    user and the namespace are obtained from the event context. This is a
    function that can only be called from a SocketIO event handler. Example::

        @socketio.on('join')
        def on_join(data):
            username = session['username']
            room = data['room']
            join_room(room)
            send(username + ' has entered the room.', room=room)

    :param room: The name of the room to join.
    """
    socketio = flask.current_app.extensions['socketio']
    socketio.server.enter_room(flask.request.sid, room,
                               namespace=flask.request.namespace)


def leave_room(room):
    """Leave a room.

    This function removes the user from a room, under the current namespace.
    The user and the namespace are obtained from the event context. This is
    a function that can only be called from a SocketIO event handler. Example::

        @socketio.on('leave')
        def on_leave(data):
            username = session['username']
            room = data['room']
            leave_room(room)
            send(username + ' has left the room.', room=room)

    :param room: The name of the room to leave.
    """
    socketio = flask.current_app.extensions['socketio']
    socketio.server.leave_room(flask.request.sid, room,
                               namespace=flask.request.namespace)


def close_room(room):
    """Close a room.

    This function removes any users that are in the given room and then deletes
    the room from the server. This is a function that can only be called from
    a SocketIO event handler.

    :param room: The name of the room to close.
    """
    socketio = flask.current_app.extensions['socketio']
    socketio.server.close_room(room, namespace=flask.request.namespace)


def rooms():
    """Return a list of the rooms the client is in.

    This function returns all the rooms the client has entered, including its
    own room, assigned by the Socket.IO server. This is a function that can
    only be called from a SocketIO event handler.
    """
    socketio = flask.current_app.extensions['socketio']
    return socketio.server.rooms(flask.request.sid,
                                 namespace=flask.request.namespace)


def disconnect(silent=False):
    """Disconnect the client.

    This function terminates the connection with the client. As a result of
    this call the client will receive a disconnect event. Example::

        @socketio.on('message')
        def receive_message(msg):
            if is_banned(session['username']):
                disconnect()
            # ...

    :param silent: close the connection, but do not actually send a disconnect
                   packet to the client.
    """
    #return flask.request.namespace.disconnect(silent)
    raise NotImplementedError()
