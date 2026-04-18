# #!/usr/bin/python3
from picamera2 import Picamera2
from libcamera import controls

def exposure_captures(exposure_list=[100000, 500000, 1000000, 2000000]):
    with Picamera2() as picam2:
        # config = picam2.create_still_configuration(raw={}, buffer_count=2)
        config = picam2.create_still_configuration(raw={})
        picam2.set_controls({'AfMode': controls.AfModeEnum.Manual, 'LensPosition': 15.0})
        picam2.configure(config)
        picam2.start()
        capture_multiple_exposures(picam2, exposure_list, config, callback_func)
        picam2.stop()
        return [f"{i}.dng" for i in range(len(exposure_list))]


def capture_multiple_exposures(picam2, exp_list, config,callback):

    def match_exp(metadata, indexed_list):
        err_factor = 0.01 # changed it to 1 or 10 to get results
        err_exp_offset = 30
        exp = metadata["ExposureTime"]
        gain = metadata["AnalogueGain"]
        for want in indexed_list:
            want_exp, _ = want
            if abs(gain - 1.0) < err_factor and abs(exp - want_exp) < want_exp * err_factor + err_exp_offset:
                return want
        return None

    indexed_list = [(exp, i) for i, exp in enumerate(exp_list)]
    while indexed_list:
        request = picam2.capture_request()
        match = match_exp(request.get_metadata(), indexed_list)
        if match is not None:
            indexed_list.remove(match)
            exp, i = match
            callback(i, exp, request, picam2, config)
        if indexed_list:
            exp, _ = indexed_list[0]
            picam2.set_controls({"ExposureTime": exp, "AnalogueGain": 1.0})
            indexed_list.append(indexed_list.pop(0))
        request.release()

def callback_func(i, wanted_exp, request, picam2, config):
    print(i, "wanted", wanted_exp, "got", request.get_metadata()["ExposureTime"])
    meta = request.get_metadata()
    exT = request.get_metadata()["ExposureTime"] 
    picam2.helpers.save_dng(request.make_buffer("raw"), meta, config['raw'], f"{i}_{exT}.dng")

exposure_captures()