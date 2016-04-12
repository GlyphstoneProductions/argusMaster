__author__ = 'breanna'


import requests
import requests.exceptions
from requests_futures.sessions import FuturesSession

import json
from kivy.app import App
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.core.text import LabelBase
from kivy.utils import get_color_from_hex
from kivy.clock import Clock
from kivy.properties import ObjectProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.accordion import Accordion
from kivy.uix.accordion import AccordionItem
from kivy.uix.popup import Popup
from kivy.uix.label import Label
from kivy.logger import Logger
import logging
import logging.handlers

class ArgusMasterApp(App):

    def __init__(self):
        super( ArgusMasterApp, self).__init__()
        self.camReg = RegServiceClient()

    def on_start(self):
        self.initLogging()
        Logger.info("ArgusMaster starting")
        self.root.ids.cameras.setApp(self)

    def on_stop(self):
        Logger.info("ArgusMaster Stopping")
        self.deactivateAllCameras()

    def activateAllCameras(self):
        self.root.ids.cameras.activateAllAsync()

    def captureAllCameras(self):
        self.root.ids.cameras.captureAllAsync(self)

    def deactivateAllCameras(self):
        self.root.ids.cameras.deactivateAll()

    def refreshCameras(self):
        cameras = self.camReg.getRegisteredCameras()
        camCol = self.root.ids.cameras
        camCol.removeAllCameras()
        for cam in cameras:
            camCol.addCamera(cam)

    def initLogging(self):
        """
        Set up logging hard-coded.
        TODO: Utilize logger.config or get paramters from centralized config file
        :return:
        """
        handler = logging.handlers.RotatingFileHandler( 'log/argus_master.log', maxBytes=256000, backupCount=2)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger = logging.getLogger()
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)


class CameraCollection(Accordion):
    """
    Represents all recognized cameras in the network
    """
    def setApp(self, app):
        self.app = app

    def removeAllCameras(self):
        self.clear_widgets()

    def addCamera(self, camreg):
        title = camreg['hostname']
        cam = CameraItem(camreg['ip'], title, camreg['registered'], self.app)
        self.add_widget( cam )
        Logger.debug("Camera {0} added".format(title))

    def activateAll(self):
        for cam in self.children:
            cam.activate()

    def activateAllAsync(self):
        for cam in self.children:
            cam.activate_start()
        for cam in self.children:
            cam.activate_show()

    def deactivateAll(self):
        for cam in self.children:
            cam.deactivate()

    def captureAllAsync(self, app):
        for cam in self.children:
            cam.capture_start()
        for cam in self.children:
            cam.capture_show()
        for cam in self.children:
            cam.fetch_stereo_images()

        app.root.ids.image_left_left.reload()
        app.root.ids.image_left_right.reload()
        app.root.ids.image_center_left.reload()
        app.root.ids.image_center_right.reload()
        app.root.ids.image_right_left.reload()
        app.root.ids.image_right_right.reload()


class CameraItem(AccordionItem):
    """
    Represents the information and state we have about the camera and handles its
    representation in the list of cameras
    """
    camera_info = ObjectProperty(None)
    activate_button = ObjectProperty(None)
    active = False
    online = False

    def __init__(self, ip, title, registered, app ):
        super( CameraItem, self).__init__()
        self.title = title
        self.id = ip # Accordion widget id property
        self.ip = ip
        self.registered = registered
        self.app = app # reference to app for lateral reference calls

        self.future = None

        self.displayInfo( None)
        self.activate_button.bind( on_press = self.on_camera_active_toggle )
        self.capture_button.bind( on_press = self.on_capture )
        self.camClient = CameraClient(ip)
        self.caminfo = self.camClient.getCameraInfo()
        if self.caminfo['success']:
            self.online = True
            self.displayInfo(self.caminfo['info'])
            self.showInactive()
        else :
            # deactivate camera buttons. (other than retry)
            Logger.warning("Camera {0} could not be contacted".format(ip))
            self.showOffline()

    def displayInfo(self, caminfo = None):
        text = "IP:  {0}\nRegistered On:\ {1}".format( self.ip, self.registered)
        if caminfo:
            for i in caminfo:
                text += "\n{0}:  {1}".format( i, caminfo[i])
        self.camera_info.text = text

    def on_camera_active_toggle(self, instance):
        if self.active:
            self.deactivate()
        else:
            self.activate()

    def on_capture(self, instance):
        self.capture()
        self.fetch_stereo_images()
        self.refreshImages()

    def refreshImages(self):
        leftimg = "image_{0}_left".format(self.title)
        rightimg = "image_{0}_right".format(self.title)
        self.app.root.ids[leftimg].reload()
        self.app.root.ids[rightimg].reload()

    #=== Activate ========================================
    def activate(self):
        if not self.active:
            result = self.camClient.activate()
            if result['success']:

                self.activate_button.text = "Deactivate"
                self.showActive()
                self.active = True
                Logger.info("camera {0} active".format(self.title))
            else:
                Logger.warning("camera activation failed: {0}", result['message'])

    def activate_start(self):
        if not self.active:
            self.future = self.camClient.activate_async(self.activate_callback)

    def activate_callback(self, sess, resp):

        Logger.debug("Activate callback: [{0}] {1} ".format(self.ip, str(resp.content) ))


    def activate_show(self):
        """
        Matching async get and display for async activate_start
        :return:
        """
        result = self.activate_get()
        if result['success']:
            self.activate_button.text = "Deactivate"
            self.showActive()
            self.active = True
            Logger.info("camera {0} active".format(self.title))
        else:
            Logger.warning("camera activation failed: {0}".format( result['message']))

    def activate_get(self):
        response = { 'success': False, 'message': '', 'info': None }
        if not self.future:
            response['message'] = 'There is NO future!'
        else:
            try:
                resp = self.future.result()
                reply = True
            except requests.exceptions.ConnectionError as e :
                Logger.warning("Could not access Camera: {0}: {1}".format(e.errno, e.strerror))
                response['message'] = 'Timeout'
                reply = False
            except requests.exceptions.RequestException as e:
                Logger.error("Error accessing Camera [{0}]: {1}".format(e.errno, e.strerror))
                response['message'] = e.strerror
                reply = False

            if reply and resp.status_code==200:
                data = resp.json()
                if data['master']['status'] == 'active' and data['slave']['status'] == 'active':
                    response['success'] = True
                    response['message'] = ''
                    response['info'] = data

        return response


    # === Capture ===================================================================

    def capture(self):
        Logger.debug("Start Capture for {0}".format(self.title))
        if self.active:
            result = self.camClient.capture()
            if result['success']:
                Logger.info("camera {0} captured".format(self.title))
            else:
                Logger.warning("camera {0} failed: {1}".format( self.title, result['message']))
        else:
            Logger.warning("Camera not active")

    def capture_start(self):
        if self.active:
            self.future = self.camClient.capture_async( self.capture_callback)
        else:
            Logger.warning("Camera not active")

    def capture_callback(self, sess, resp):

        Logger.debug("Capture callback: [{0}] ".format(self.ip ))


    def capture_show(self):
        result = self.camClient.capture_get(self.future)
        if result['success']:
            Logger.info("camera {0} captured".format(self.title))
        else:
            Logger.warning("camera {0} capture failed: {1}".format( self.title, result['message']))


    def fetch_stereo_images(self):
        """
        Fetch master and slave (left and right) images last captured by the camera

        :return:
        """
        result = self.camClient.getfile( "images/master.jpg", "camimages/{0}/left.jpg".format(self.title))
        result = self.camClient.getfile( "images/slave.jpg", "camimages/{0}/right.jpg".format(self.title))

    # === Deactivate ================================================================
    def deactivate(self):

        result = self.camClient.deactivate()
        if result['success']:
            self.activate_button.text = "Activate"
            self.showInactive()
            self.active = False
            Logger.info("camera {0} inactive".format(self.title))
        else:
            Logger.warning("camera deactivation failed: {0}", result['message'])

    # === Helpers ===================================================================
    def showActive(self):
        self.background_normal = 'images/active_button_normal.png'
        self.background_selected = 'images/active_button_down.png'

    def showInactive(self):
        self.background_normal = 'images/button_normal.png'
        self.background_selected = 'images/button_down.png'

    def showOffline(self):
        self.background_normal = 'images/alert_button_normal.png'
        self.background_selected = 'images/alert_button_down.png'

    def getLogger(self):
        return logging.getLogger('argusmaster.camera_item')



class RegServiceClient:

    def getRegisteredCameras(self):
        cameras = {}
        try:
            resp = requests.get("http://localhost:8082/registration", timeout=10.0)
            reply = True
        except requests.exceptions.ConnectionError:
            Logger.warning("Could not access Registration Server")
            reply = False
        except requests.exceptions.RequestException as e:
            Logger.error("Error accessing Registration Server [{0}]: {1}".format(e.errno, e.strerror))
            reply = False

        if reply and resp.status_code==200:
            data = resp.json()
            Logger.info("Registration Fetch Successful")
            datas = json.dumps(data)
            Logger.debug(datas)
            cameras = data['cameras']

        return cameras


class CameraClient:

    def __init__(self, ip):
        self.ip = ip
        self.session = FuturesSession(max_workers=10)

    def getServiceUrl(self):
        return "http://{0}:8081/".format(self.ip)

    def getCameraInfo(self):

        response = { 'success': False }
        try:
            url = self.getServiceUrl()
            Logger.debug("Getting camera info: {0}".format(url))
            resp = requests.get(url, timeout=10.0)
            reply = True
        except requests.exceptions.ConnectionError as e :
            Logger.warning("Could not access Camera: {0}: {1}".format(e.errno, e.strerror))
            response['message'] = 'Connection Error'
            reply = False
        except requests.exceptions.Timeout as e :
            Logger.warning("Timeout accessing Camera: {0}: {1}".format(e.errno, e.strerror))
            response['message'] = 'Timeout'
            reply = False
        except requests.exceptions.RequestException as e:
            Logger.error("Error accessing Camera [{0}]: {1}".format(type(e).__name__, e.strerror))
            reply = False


        if reply and resp.status_code==200:
            data = resp.json()
            datas = json.dumps(data)
            Logger.debug(datas)
            response['success'] = True
            response['message'] = ''
            response['info'] = data

        return response

    def activate(self):
        response = { 'success': False, 'message': '', 'info': None }
        session = self.session
        try:
            url = self.getServiceUrl() + 'camera/on'
            future = session.get(url, timeout=5.0)
            resp = future.result()
            reply = True
        except requests.exceptions.ConnectionError as e :
            Logger.warning("Could not access Camera: {0}: {1}".format(e.errno, e.strerror))
            response['message'] = 'Timeout'
            reply = False
        except requests.exceptions.RequestException as e:
            Logger.error("Error accessing Camera [{0}]: {1}".format(e.errno, e.strerror))
            response['message'] = e.strerror
            reply = False

        if reply and resp.status_code==200:
            data = resp.json()
            if data['master']['status'] == 'active' and data['slave']['status'] == 'active':
                response['success'] = True
                response['message'] = ''
                response['info'] = data

        return response

    def activate_async(self, callback):
        url = self.getServiceUrl() + 'camera/on'
        future = self.session.get(url, timeout=5.0, background_callback=callback )
        return future

    def capture(self):
        response = { 'success': False, 'message': '', 'info': None }
        session = self.session
        try:
            url = self.getServiceUrl() + 'camera/capture'
            Logger.debug("GET {0}".format(url))
            future = session.get(url, timeout=10.0)
            resp = future.result()
            Logger.debug("Capture response")
            reply = True
        except requests.exceptions.ConnectionError as e :
            Logger.warning("Could not access Camera: {0}: {1}".format(e.errno, e.strerror))
            response['message'] = 'Timeout'
            reply = False
        except requests.exceptions.RequestException as e:
            Logger.error("Error accessing Camera [{0}]: {1}".format(e.errno, e.strerror))
            response['message'] = e.strerror
            reply = False

        if reply and resp.status_code==200:
            data = resp.json()
            Logger.debug("Capture Success")
            if data['master']['status'] == 'success' and data['slave']['status'] == 'success':
                response['success'] = True
                response['message'] = ''
                response['info'] = data

        return response

    def capture_async(self, callback):
        url = self.getServiceUrl() + 'camera/capture'
        future = self.session.get(url, timeout=5.0, background_callback=callback )
        return future

    def capture_get(self, future):
        response = { 'success': False, 'message': '', 'info': None }
        if not future:
            response['message'] = 'There is NO future!'
        else:
            try:
                resp = future.result()
                reply = True
            except requests.exceptions.ConnectionError as e :
                Logger.warning("Could not access Camera: {0} [{1}]: {2}".format(self.ip, e.errno, e.strerror))
                response['message'] = 'Timeout'
                reply = False
            except requests.exceptions.RequestException as e:
                Logger.error("Error accessing Camera: {0} [{1}]: {2}".format(self.ip, e.errno, e.strerror))
                response['message'] = e.strerror
                reply = False

            if reply and resp.status_code==200:
                Logger.debug("Capture {0} complete code 200".format( self.ip))
                data = resp.json()
                if data['master']['status'] == 'success' and data['slave']['status'] == 'success':
                    response['success'] = True
                    response['message'] = ''
                    response['info'] = data

        return response

    def deactivate(self):
        response = { 'success': False, 'message': '', 'info': None }
        try:
            url = self.getServiceUrl() + 'camera/off'
            resp = requests.get(url, timeout=5.0)
            reply = True
        except requests.exceptions.ConnectionError as e :
            Logger.warning("Could not access Camera: {0}: {1}".format(e.errno, e.strerror))
            response['message'] = 'Timeout'
            reply = False
        except requests.exceptions.RequestException as e:
            Logger.error("Error accessing Camera [{0}]: {1}".format(e.errno, e.strerror))
            response['message'] = e.strerror
            reply = False

        if reply and resp.status_code==200:
            data = resp.json()
            if data['master']['status'] == 'inactive' and data['slave']['status'] == 'inactive':
                response['success'] = True
                response['message'] = ''
                response['info'] = data

        return response

    def getfile(self, remoteFilename, localFilename, fromSlave = False ):
        fromwhere = "master" if fromSlave == False else "slave"
        try:
            url = self.getServiceUrl() + "files/{0}/{1}".format(fromwhere, remoteFilename)
            Logger.debug("Getting file: {0}".format(url))
            resp = requests.get(url, stream = True)
            reply = True
        except requests.exceptions.RequestException as e:
            Logger.error("Error accessing Camera [{0}]: {1}".format(type(e).__name__, e.strerror))
            reply = False

        if reply and resp.status_code==200:
            Logger.debug("Starting download of {0}".format(localFilename))

            with open(localFilename, 'wb') as f:
                for block in resp.iter_content(1024):
                    f.write(block)

            Logger.debug("Finished download!")
            return True
        else:
            return False

if __name__ == '__main__':
    Window.size = (1200, 800)
    ArgusMasterApp().run()


