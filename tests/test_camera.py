import ctypes as C
import errno
import unittest
from unittest.mock import patch

from racevideo import camera


class Driver:
    """Fake kernel ioctl boundary; no physical controls touched by unit tests."""
    def __init__(self):
        self.values = {10: 32, 20: 3, 30: 51}
        self.writes = []

    def ioctl(self, fd, operation, data, mutate):
        if operation == camera.QUERY:
            q = camera.Query.from_buffer(data)
            if q.id & camera.NEXT:
                after = q.id & ~camera.NEXT
                found = next((i for i in (10, 20, 30) if i > after), None)
                if found is None: raise OSError(errno.EINVAL, 'end')
                q.id = found
            if q.id not in self.values: raise OSError(errno.EINVAL, 'unsupported')
            q.type = 3 if q.id == 20 else 1
            q.minimum, q.maximum, q.step = (0, 3, 1) if q.id == 20 else (0, 255, 17 if q.id == 30 else 1)
            q.name = {10:b'Contrast',20:b'Exposure mode',30:b'Focus'}[q.id]
            q.flags = 16 if q.id == 30 else 0
        elif operation == camera.QUERY_MENU:
            q = camera.Menu.from_buffer(data)
            if q.index not in (1, 3): raise OSError(errno.EINVAL, 'hole')
            text = b'Manual' if q.index == 1 else b'Auto'
            for i,v in enumerate(text): q.data[i]=v
        elif operation == camera.GET:
            q = camera.Value.from_buffer(data)
            q.value = self.values[q.id]
        elif operation == camera.SET:
            q = camera.Value.from_buffer(data)
            self.writes.append((q.id, q.value))
            self.values[q.id] = q.value
        else:
            raise AssertionError(operation)
        return 0


class CameraTests(unittest.TestCase):
    def setUp(self):
        self.driver = Driver()
        self.camera = camera.CameraControls.__new__(camera.CameraControls)
        self.camera.fd = -1
        self.patcher = patch('racevideo.camera.fcntl.ioctl', self.driver.ioctl)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_linux_uapi_layout(self):
        self.assertEqual((C.sizeof(camera.Query), C.sizeof(camera.Menu), C.sizeof(camera.Value)), (68,44,8))
        self.assertEqual(camera.QUERY, 0xC0445624)
        self.assertEqual(C.sizeof(camera.Capability),104)

    def test_discovery_handles_menu_holes_and_inactive_focus(self):
        controls = self.camera.enumerate()
        self.assertEqual(len(controls), 3)
        self.assertEqual([c['value'] for c in controls[1]['choices']], [1,3])
        self.assertFalse(controls[2]['writable'])
        self.assertIn('automatic', controls[2]['disabled_reason'])

    def test_write_is_read_back_and_invalid_values_never_reach_driver(self):
        self.assertEqual(self.camera.set(10, 40), 40)
        for cid,value in ((10,256),(20,2),(30,51)):
            with self.assertRaises(ValueError): self.camera.set(cid,value)
        self.assertEqual(self.driver.writes,[(10,40)])

    def test_exposure_units(self):
        self.assertIn('1/2000s', camera.format_value(camera.EXPOSURE,5))


if __name__=='__main__': unittest.main()
