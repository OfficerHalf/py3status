import os
import imp
import inspect

from threading import Thread, Timer
from collections import OrderedDict
from syslog import syslog, LOG_INFO
from time import time

from py3status.py3 import Py3, PY3_CACHE_FOREVER
from py3status.profiling import profile


class Module(Thread):
    """
    This class represents a user module (imported file).
    It is responsible for executing it every given interval and
    caching its output based on user will.
    """

    PARAMS_NEW = 'new'
    PARAMS_LEGACY = 'legacy'

    def __init__(self, module, user_modules, py3_wrapper):
        """
        We need quite some stuff to occupy ourselves don't we ?
        """
        Thread.__init__(self)
        self.cache_time = None
        self.click_events = False
        self.config = py3_wrapper.config
        self.has_kill = False
        self.i3status_thread = py3_wrapper.i3status_thread
        self.last_output = []
        self.lock = py3_wrapper.lock
        self.methods = OrderedDict()
        self.module_class = None
        self.module_full_name = module
        self.module_inst = ''.join(module.split(' ')[1:])
        self.module_name = module.split(' ')[0]
        self.new_update = False
        self.module_full_name = module
        self.nagged = False
        self.sleeping = False
        self.timer = None

        # py3wrapper this is private and any modules accessing their instance
        # should only use it on the understanding that it is not supported.
        self._py3_wrapper = py3_wrapper
        #
        self.set_module_options(module)
        self.load_methods(module, user_modules)

    def __repr__(self):
        return '<Module {}>'.format(self.module_full_name)

    @staticmethod
    def load_from_file(filepath):
        """
        Return user-written class object from given path.
        """
        class_inst = None
        expected_class = 'Py3status'
        module_name, file_ext = os.path.splitext(os.path.split(filepath)[-1])
        if file_ext.lower() == '.py':
            py_mod = imp.load_source(module_name, filepath)
            if hasattr(py_mod, expected_class):
                class_inst = py_mod.Py3status()
        return class_inst

    @staticmethod
    def load_from_namespace(module_name):
        """
        Load a py3status bundled module.
        """
        class_inst = None
        name = 'py3status.modules.{}'.format(module_name)
        py_mod = __import__(name)
        components = name.split('.')
        for comp in components[1:]:
            py_mod = getattr(py_mod, comp)
        class_inst = py_mod.Py3status()
        return class_inst

    def force_update(self):
        """
        Forces an update of the module.
        """
        # clear cached_until for each method to allow update
        for meth in self.methods:
            self.methods[meth]['cached_until'] = time()
            if self.config['debug']:
                syslog(LOG_INFO, 'clearing cache for method {}'.format(meth))
        # cancel any existing timer
        if self.timer:
            self.timer.cancel()
        # get the thread to update itself
        self.timer = Timer(0, self.run)
        self.timer.start()

    def sleep(self):
        self.sleeping = True
        # cancel any existing timer
        if self.timer:
            self.timer.cancel()

    def wake(self):
        self.sleeping = False
        cache_time = self.cache_time
        # new style modules can signal they want to cache forever
        if cache_time == PY3_CACHE_FOREVER:
            return
        # restart
        delay = max(cache_time - time(), 0)
        self.timer = Timer(delay, self.run)
        self.timer.start()

    def set_updated(self):
        """
        Mark the module as updated
        """
        self._py3_wrapper.notify_update(self.module_full_name)

    def get_latest(self):
        output = []
        for method in self.methods.values():
            output.append(method['last_output'])
        return output

    def set_module_options(self, module):
        """
        Set universal module options to be interpreted by i3bar
        https://i3wm.org/i3status/manpage.html#_universal_module_options
        """
        self.module_options = {}
        mod_config = self.i3status_thread.config.get(module, {})

        if 'min_width' in mod_config:
            self.module_options['min_width'] = mod_config['min_width']

        if 'separator' in mod_config:
            separator = mod_config['separator']
            if not isinstance(separator, bool):
                raise TypeError("invalid 'separator' attribute, should be a bool")

            self.module_options['separator'] = separator

        if 'separator_block_width' in mod_config:
            separator_block_width = mod_config['separator_block_width']
            if not isinstance(separator_block_width, int):
                raise TypeError("invalid 'separator_block_width' attribute, should be an int")

            self.module_options['separator_block_width'] = separator_block_width

        if 'align' in mod_config:
            align = mod_config['align']
            if not (isinstance(align, str) and align.lower() in ("left", "center", "right")):
                raise ValueError("invalid 'align' attribute, valid values are: left, center, right")

            self.module_options['align'] = align

    def _params_type(self, method_name, instance):
        """
        Check to see if this is a legacy method or shiny new one

        legacy update method:
            def update(self, i3s_output_list, i3s_config):
                ...

        new update method:
            def update(self):
                ...

        Returns False if the method does not exist,
        else PARAMS_NEW or PARAMS_LEGACY
        """

        method = getattr(instance, method_name, None)
        if not method:
            return False

        # Check the parameters we simply count the number of args and don't
        # allow any extras like keywords.
        arg_count = 1
        # on_click method has extra events parameter
        if method_name == 'on_click':
            arg_count = 2
        args, vargs, kw, defaults = inspect.getargspec(method)
        if len(args) == arg_count and not vargs and not kw:
            return self.PARAMS_NEW
        else:
            return self.PARAMS_LEGACY

    def load_methods(self, module, user_modules):
        """
        Read the given user-written py3status class file and store its methods.
        Those methods will be executed, so we will deliberately ignore:
            - private methods starting with _
            - decorated methods such as @property or @staticmethod
            - 'on_click' methods as they'll be called upon a click_event
            - 'kill' methods as they'll be called upon this thread's exit
        """
        # user provided modules take precedence over py3status provided modules
        if self.module_name in user_modules:
            include_path, f_name = user_modules[self.module_name]
            syslog(LOG_INFO,
                   'loading module "{}" from {}{}'.format(module, include_path,
                                                          f_name))
            class_inst = self.load_from_file(include_path + f_name)
        # load from py3status provided modules
        else:
            syslog(LOG_INFO,
                   'loading module "{}" from py3status.modules.{}'.format(
                       module, self.module_name))
            class_inst = self.load_from_namespace(self.module_name)

        if class_inst:
            self.module_class = class_inst

            # apply module configuration from i3status config
            mod_config = self.i3status_thread.config.get(module, {})
            for config, value in mod_config.items():
                # names starting with '.' are private
                if not config.startswith('.'):
                    setattr(self.module_class, config, value)

            # Add the py3 module helper if modules self.py3 is not defined
            if not hasattr(self.module_class, 'py3'):
                setattr(self.module_class, 'py3', Py3(self))

            # get the available methods for execution
            for method in sorted(dir(class_inst)):
                if method.startswith('_'):
                    continue
                else:
                    m_type = type(getattr(class_inst, method))
                    if 'method' in str(m_type):
                        params_type = self._params_type(method, class_inst)
                        if method == 'on_click':
                            self.click_events = params_type
                        elif method == 'kill':
                            self.has_kill = params_type
                        else:
                            # the method_obj stores infos about each method
                            # of this module.
                            method_obj = {
                                'cached_until': time(),
                                'call_type': params_type,
                                'instance': None,
                                'last_output': {
                                    'name': method,
                                    'full_text': ''
                                },
                                'method': method,
                                'name': None
                            }
                            self.methods[method] = method_obj

        # done, syslog some debug info
        if self.config['debug']:
            syslog(LOG_INFO,
                   'module "{}" click_events={} has_kill={} methods={}'.format(
                       module, self.click_events, self.has_kill,
                       self.methods.keys()))

    def click_event(self, event):
        """
        Execute the 'on_click' method of this module with the given event.
        """
        try:
            click_method = getattr(self.module_class, 'on_click')
            if self.click_events == self.PARAMS_NEW:
                # new style modules
                click_method(event)
            else:
                # legacy modules had extra parameters passed
                click_method(self.i3status_thread.json_list,
                             self.i3status_thread.config['general'], event)
            self.set_updated()
        except Exception:
            msg = 'on_click event in `{}` failed'.format(self.module_full_name)
            self._py3_wrapper.report_exception(msg)

    @profile
    def run(self):
        """
        On a timely fashion, execute every method found for this module.
        We will respect and set a cache timeout for each method if the user
        didn't already do so.
        We will execute the 'kill' method of the module when we terminate.
        """
        # cancel any existing timer
        if self.timer:
            self.timer.cancel()

        if self.lock.is_set():
            cache_time = None
            # execute each method of this module
            for meth, obj in self.methods.items():
                my_method = self.methods[meth]

                # always check the lock
                if not self.lock.is_set():
                    break

                # respect the cache set for this method
                if time() < obj['cached_until']:
                    if not cache_time or obj['cached_until'] < cache_time:
                        cache_time = obj['cached_until']
                    continue

                try:
                    # execute method and get its output
                    method = getattr(self.module_class, meth)
                    if my_method['call_type'] == self.PARAMS_NEW:
                        # new style modules
                        response = method()
                    else:
                        # legacy modules had parameters passed
                        response = method(
                            self.i3status_thread.json_list,
                            self.i3status_thread.config['general'])

                    if isinstance(response, dict):
                        # this is a shiny new module giving a dict response
                        result = response
                    elif isinstance(response, tuple):
                        # this is an old school module reporting its position
                        position, result = response
                        if not isinstance(result, dict):
                            raise TypeError('response should be a dict')
                    else:
                        raise TypeError('response should be a dict')

                    # validate the response
                    if 'full_text' not in result:
                        raise KeyError('missing "full_text" key in response')
                    else:
                        result['instance'] = self.module_inst
                        result['name'] = self.module_name

                    # set universal module options in result
                    result.update(self.module_options)

                    # initialize method object
                    if my_method['name'] is None:
                        my_method['name'] = result['name']
                        if 'instance' in result:
                            my_method['instance'] = result['instance']
                        else:
                            my_method['instance'] = result['name']

                    # update method object cache
                    if 'cached_until' in result:
                        cached_until = result['cached_until']
                    else:
                        cached_until = time() + self.config['cache_timeout']
                    my_method['cached_until'] = cached_until
                    if not cache_time or cached_until < cache_time:
                        cache_time = cached_until

                    # update method object output
                    my_method['last_output'] = result

                    # mark module as updated
                    self.set_updated()

                    # debug info
                    if self.config['debug']:
                        syslog(LOG_INFO,
                               'method {} returned {} '.format(meth, result))
                except Exception:
                    msg = 'Instance `{}`, user method `{}` failed'
                    msg = msg.format(self.module_full_name, meth)
                    notify = not self.nagged
                    self._py3_wrapper.report_exception(msg, notify_user=notify)
                    self.nagged = True

            if cache_time is None:
                cache_time = time() + self.config['cache_timeout']
            self.cache_time = cache_time
            # new style modules can signal they want to cache forever
            if cache_time == PY3_CACHE_FOREVER:
                return
            # don't be hasty mate
            # set timer to do update next time one is needed
            if not self.sleeping:
                delay = max(cache_time - time(), self.config['minimum_interval'])
                self.timer = Timer(delay, self.run)
                self.timer.start()

    def kill(self):
        # stop timer if exists
        if self.timer:
            self.timer.cancel()
        # check and execute the 'kill' method if present
        if self.has_kill:
            try:
                kill_method = getattr(self.module_class, 'kill')
                if self.has_kill == self.PARAMS_NEW:
                    kill_method()
                else:
                    # legacy call parameters
                    kill_method(self.i3status_thread.json_list,
                                self.i3status_thread.config['general'])
            except Exception:
                # this would be stupid to die on exit
                pass
