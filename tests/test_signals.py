import unittest
from signals import fair_value,build_signal
class SignalTests(unittest.TestCase):
    def test_fair_bounded(self):
        f,c=fair_value(.5,[{"p":.4},{"p":.5},{"p":.6}]*10)
        self.assertTrue(.001<=f<=.999); self.assertTrue(.5<=c<=.96)
    def test_signal_shape(self):
        s=build_signal(.30,[{"p":.5}]*20)
        self.assertIn(s.side,("YES","NO")); self.assertTrue(.001<=s.fair<=.999)
if __name__=="__main__": unittest.main()
