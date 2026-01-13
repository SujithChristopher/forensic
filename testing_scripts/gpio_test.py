#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  gpiotest_pi5.py
#
#  Original Copyright 2016 Roman Mindlin <Roman@Mindlin.ru>
#  Modified for Raspberry Pi 5 with gpiod
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#

try:
    import gpiod
except RuntimeError:
    print("Error importing gpiod! This is probably because you need to install the library.")
    print("You can install it using: sudo apt install python3-libgpiod")

import sys
import getopt
import curses
import random
import time
import threading
import os
import subprocess
from datetime import datetime

# Global variables
gpio_state = []
gpio_inout = []
gpio_pud = []
on_pause = 0
log = []
debounce = 200
lines = []
gpio_num = 0
gpio_ch = []
chip = None
RaspiModel = ""
monitor_threads = []
stop_monitoring = False

def get_pi_model():
    """Get Raspberry Pi model information"""
    try:
        process = subprocess.Popen(['cat', '/proc/cpuinfo'], stdout=subprocess.PIPE)
        output, _ = process.communicate()
        output = output.decode('utf-8')
        
        if "Raspberry Pi 5" in output:
            return "Raspberry Pi 5", 26
        
        # Get revision code
        for line in output.split('\n'):
            if line.startswith('Revision'):
                revision = line.split(':')[1].strip().lower()
                return get_model_from_revision(revision)
    except Exception as e:
        print(f"Error getting Pi model: {e}")
    
    return "Unknown Model", 26

def get_model_from_revision(revision):
    """Get model and GPIO count from revision code"""
    models = {
        "0002": ("Model B Revision 1.0 256Mb", 17),
        "0003": ("Model B Revision 1.0 + ECN0001 256Mb", 17),
        "0004": ("Model B Revision 2.0 256Mb", 17),
        "0005": ("Model B Revision 2.0 256Mb", 17),
        "0006": ("Model B Revision 2.0 256Mb", 17),
        "0007": ("Model A 256Mb", 17),
        "0008": ("Model A 256Mb", 17),
        "0009": ("Model A 256Mb", 17),
        "000d": ("Model B Revision 2.0 512Mb", 17),
        "000e": ("Model B Revision 2.0 512Mb", 17),
        "e": ("Model B Revision 2.0 512Mb", 17),
        "000f": ("Model B Revision 2.0 512Mb", 17),
        "0010": ("Model B+ 512Mb", 26),
        "0012": ("Model A+ 256Mb", 26),
        "0013": ("Model B+ 512Mb", 26),
        "13": ("Model B+ 512Mb", 26),
        "0015": ("Model A+ 256/512Mb", 26),
        "a01040": ("2 Model B Revision 1.0 1Gb", 26),
        "a01041": ("2 Model B Revision 1.1 1Gb", 26),
        "a21041": ("2 Model B Revision 1.1 1Gb", 26),
        "a22042": ("2 Model B (with BCM2837) 1Gb", 26),
        "900021": ("Model A+ 512Mb", 26),
        "900032": ("Model B+ 512Mb", 26),
        "900092": ("Zero Revision 1.2 512Mb", 26),
        "900093": ("Zero Revision 1.3 512Mb", 26),
        "920093": ("Zero Revision 1.3 512Mb", 26),
        "9000c1": ("Zero W Revision 1.1 512Mb", 26),
        "a02082": ("3 Model B 1Gb", 26),
        "a22082": ("3 Model B 1Gb", 26),
        "a32082": ("3 Model B 1Gb", 26),
        "a020d3": ("3 Model B+ 1Gb", 26),
        "9020e0": ("3 Model A+ 512Mb", 26),
        "a03111": ("4 Model B 1Gb", 26),
        "b03111": ("4 Model B 2Gb", 26),
        "b03112": ("4 Model B 2Gb", 26),
        "bo3114": ("4 Model B 2Gb", 26),
        "b03115": ("4 Model B 2Gb", 26),
        "c03111": ("4 Model B 4Gb", 26),
        "c03112": ("4 Model B 4Gb", 26),
        "c03114": ("4 Model B 4Gb", 26),
        "c03115": ("4 Model B Revision 1.5 4Gb", 26),
        "d03114": ("4 Model B 8Gb", 26),
        "c03130": ("Pi 400 4Gb", 26),
        "b03140": ("Compute Module 4 2Gb", 26),
        # Add Raspberry Pi 5 revisions
        "c04170": ("5 Model B 4Gb", 26),
        "d04170": ("5 Model B 8Gb", 26),
    }
    return models.get(revision, ("not supported", 17))

def termOn():
    # Enable character buffering and echo
    curses.nocbreak()
    curses.echo()

def termOff():
    # Disable character buffering and echo
    curses.cbreak()
    curses.noecho()

def MainScreen():
    # Draw main screen
    # coords - screen position of placeholders for pin states
    coords = [[6,15],[7,15],[8,15],[9,15],[10,15],[11,15],[12,15],[13,15],[14,15],
            [6,42],[7,42],[8,42],[9,42],[10,42],[11,42],[12,42],[13,42],[14,42],
            [6,69],[7,69],[8,69],[9,69],[10,69],[11,69],[12,69],[13,69]]

    myscreen.erase()
    myscreen.addstr(1,0, "--------------------------------------------------------------------------------")
    myscreen.addstr(2,0, "|                    * Raspberry Pi 5 GPIO monitor (gpiod) *                   |")
    myscreen.addstr(3,0, "--------------------------------------------------------------------------------")
    myscreen.addstr(4,0, "|                                                      *   Debounce            |")
    myscreen.addstr(4,2, RaspiModel + " detected (" + str(gpio_num) + " lines)")
    myscreen.addstr(4,68, str(debounce) + " ms")
    myscreen.addstr(5,0, "--------------------------------------------------------------------------------")
    if (gpio_num == 17):
        myscreen.addstr(6,0, "|     GPIO0  =           |      GPIO15  =            |                         |")
        myscreen.addstr(7,0, "|     GPIO1  =           |      GPIO17  =            |                         |")
        myscreen.addstr(8,0, "|     GPIO4  =           |      GPIO18  =            |                         |")
        myscreen.addstr(9,0, "|     GPIO7  =           |      GPIO21  =            |                         |")
        myscreen.addstr(10,0, "|     GPIO8  =           |      GPIO22  =            |                         |")
        myscreen.addstr(11,0, "|     GPIO9  =           |      GPIO23  =            |                         |")
        myscreen.addstr(12,0, "|     GPIO10 =           |      GPIO24  =            |                         |")
        myscreen.addstr(13,0, "|     GPIO11 =           |      GPIO25  =            |                         |")
        myscreen.addstr(14,0, "|     GPIO14 =           |                           |                         |")
    else:
        myscreen.addstr(6,0, "|     GPIO2  =           |      GPIO11  =            |      GPIO20 =           |")
        myscreen.addstr(7,0, "|     GPIO3  =           |      GPIO12  =            |      GPIO21 =           |")
        myscreen.addstr(8,0, "|     GPIO4  =           |      GPIO13  =            |      GPIO22 =           |")
        myscreen.addstr(9,0, "|     GPIO5  =           |      GPIO14  =            |      GPIO23 =           |")
        myscreen.addstr(10,0, "|     GPIO6  =           |      GPIO15  =            |      GPIO24 =           |")
        myscreen.addstr(11,0, "|     GPIO7  =           |      GPIO16  =            |      GPIO25 =           |")
        myscreen.addstr(12,0, "|     GPIO8  =           |      GPIO17  =            |      GPIO26 =           |")
        myscreen.addstr(13,0, "|     GPIO9  =           |      GPIO18  =            |      GPIO27 =           |")
        myscreen.addstr(14,0, "|     GPIO10 =           |      GPIO19  =            |                         |")
    myscreen.addstr(15,0,  "--------------------------------------------------------------------------------")
    myscreen.addstr(21,0,  "--------------------------------------------------------------------------------")
    myscreen.addstr(23,0,  "Q = Quit  P = Pause  D = Debounce  U = pullUp  O = Output I = Input")

    # Print states and pullup status
    for i in range(gpio_num):
        state_text = "True" if gpio_state[i] else "False"
        state_text = state_text + ("(^)" if gpio_pud[i] else "(v)")
        myscreen.addstr(coords[i][0], coords[i][1], state_text,
                      curses.A_REVERSE if gpio_inout[i] else curses.A_NORMAL)

    # Activity indicator
    myscreen.addstr(0,0, chr(int(random.random()*32) + 32))

    # Print log strings
    logwindow.erase()
    for i in range(0,5):
        logwindow.insstr(i,0,log[i])

    # Set cursor position
    myscreen.move(22,0)
    myscreen.refresh()

def SendToLog(LogMessage):
    # Rotate log lines
    global log
    for i in range(0,4):
        log[i] = log[i+1]
    log[4] = LogMessage

def PrintMsg(Msg):
    # Print messages on bottom line of screen
    msgwindow.erase()
    msgwindow.addstr(Msg)
    msgwindow.refresh()

def CheckKeys():
    # Keyboard events
    global debounce
    global on_pause

    myscreen.nodelay(1)
    key = myscreen.getch()
    myscreen.nodelay(0)

    if key == ord('q') or key == ord('Q'):
        raise KeyboardInterrupt
    elif key == ord('p') or key == ord('P'):
        PrintMsg("Paused. Press P again to continue")
        on_pause = 1
        while on_pause:
            key = msgwindow.getch()
            if key == ord('p') or key == ord('P'):
                on_pause = 0
    elif key == ord('d') or key == ord('D'):
        try:
            termOn()
            PrintMsg("Enter debounce value (ms): ")
            debounce_ = int(msgwindow.getstr())
            if (debounce_ < 0 or debounce_ > 5000):
                raise ValueError
            if (debounce_ != debounce):
                debounce = debounce_
                initGpio()
            termOff()
        except ValueError:
            PrintMsg("Value not in range")
            termOff()
            msgwindow.getch()
    elif key == ord('u') or key == ord('U'):
        try:
            termOn()
            PrintMsg("Enter GPIO line number: ")
            channel = int(msgwindow.getstr())
            if not (channel in gpio_ch):
                raise ValueError
            num = gpio_ch.index(channel)
            if (gpio_inout[num]):
                raise IOError
            PrintMsg("Enter 0 for Pull Down or 1 for Pull Up: ")
            pud = int(msgwindow.getstr())
            if (pud != 1 and pud != 0):
                raise ValueError
            gpio_pud[num] = pud
            initGpio()
            termOff()
        except ValueError:
            PrintMsg("Value not in range")
            termOff()
            msgwindow.getch()
        except IOError:
            PrintMsg("Output line cannot be pulled up")
            termOff()
            msgwindow.getch()
    elif key == ord('o') or key == ord('O'):
        try:
            termOn()
            PrintMsg("Enter GPIO line number: ")
            channel = int(msgwindow.getstr())
            if not (channel in gpio_ch):
                raise ValueError
            num = gpio_ch.index(channel)
            PrintMsg("Enter 0 for LOW or 1 for HIGH: ")
            val = int(msgwindow.getstr())
            if (val != 1 and val != 0):
                raise ValueError
            gpio_inout[num] = 1
            gpio_state[num] = val
            
            # Set the line to output
            if lines[num]:
                lines[num].release()
            
            lines[num] = chip.get_line(channel)
            lines[num].request(consumer="gpiotest", type=gpiod.LINE_REQ_DIR_OUT)
            lines[num].set_value(val)
            
            termOff()
        except ValueError:
            PrintMsg("Value not in range")
            termOff()
            msgwindow.getch()
        except Exception as e:
            PrintMsg(f"Error: {str(e)}")
            termOff()
            msgwindow.getch()
    elif key == ord('i') or key == ord('I'):
        try:
            termOn()
            PrintMsg("Enter GPIO line number: ")
            channel = int(msgwindow.getstr())
            if not (channel in gpio_ch):
                raise ValueError
            num = gpio_ch.index(channel)
            gpio_inout[num] = 0
            initGpio()
            termOff()
        except ValueError:
            PrintMsg("Value not in range")
            termOff()
            msgwindow.getch()

def monitor_gpio(channel, index):
    """Monitor a GPIO pin for changes"""
    global gpio_state, on_pause, stop_monitoring
    
    # Create a new chip for this thread
    thread_chip = gpiod.Chip("gpiochip4")
    line = thread_chip.get_line(channel)
    
    # Determine bias based on pullup/pulldown
    if gpio_pud[index]:
        bias = gpiod.LINE_BIAS_PULL_UP
    else:
        bias = gpiod.LINE_BIAS_PULL_DOWN
    
    try:
        line.request(consumer=f"monitor_{channel}", type=gpiod.LINE_REQ_EV_BOTH_EDGES, flags=gpiod.LINE_REQ_FLAG_BIAS_DISABLE)
        
        # Set initial state
        initial_value = line.get_value()
        gpio_state[index] = initial_value
        
        while not stop_monitoring:
            # Wait for events with timeout
            if line.event_wait(timeout=0.1):
                event = line.event_read()
                if not on_pause:
                    if event.event_type == gpiod.LINE_EVENT_RISING_EDGE:
                        gpio_state[index] = 1
                        log_msg = f"{datetime.now().strftime('%Y-%b-%d %H:%M:%S')}: Channel {channel} changed (on)"
                    else:
                        gpio_state[index] = 0
                        log_msg = f"{datetime.now().strftime('%Y-%b-%d %H:%M:%S')}: Channel {channel} changed (off)"
                    SendToLog(log_msg)
            time.sleep(debounce / 1000.0)  # Debounce time
    except Exception as e:
        SendToLog(f"Error monitoring GPIO {channel}: {str(e)}")
    finally:
        try:
            line.release()
        except:
            pass

def initGpio(firstrun=0):
    """Initialize GPIO lines"""
    global chip, lines, monitor_threads, stop_monitoring
    
    curses.savetty()  # Save screen

    # Stop any existing monitoring threads
    if not firstrun and monitor_threads:
        stop_monitoring = True
        for thread in monitor_threads:
            if thread.is_alive():
                thread.join(1.0)
        stop_monitoring = False
        monitor_threads = []

    # Release all lines
    for line in lines:
        if line:
            try:
                line.release()
            except:
                pass
    
    # Reinitialize chip
    if chip:
        del chip
    chip = gpiod.Chip("gpiochip4")
    
    # Initialize lines array
    lines = [None] * len(gpio_ch)
    
    # Set up GPIO pins for monitoring or output
    for i, channel in enumerate(gpio_ch):
        if not gpio_inout[i]:  # Input mode
            # Don't request the line here, we'll do it in the monitoring thread
            thread = threading.Thread(target=monitor_gpio, args=(channel, i))
            thread.daemon = True
            monitor_threads.append(thread)
            thread.start()
        else:  # Output mode
            # Set up output line
            lines[i] = chip.get_line(channel)
            lines[i].request(consumer="gpiotest", type=gpiod.LINE_REQ_DIR_OUT)
            lines[i].set_value(gpio_state[i])

    curses.resetty()  # Restore screen

def main():
    global myscreen, logwindow, msgwindow, gpio_num, gpio_ch, debounce
    global gpio_state, gpio_inout, gpio_pud, on_pause, log, RaspiModel, chip
    
    try:
        # Check command line options
        opts, args = getopt.getopt(sys.argv[1:], "hg:", ["help", "gpio_num="])
    except getopt.GetoptError:
        print('Usage: gpiotest_pi5.py [--gpio_num <num>]')
        sys.exit(2)
        
    # Process command line arguments
    for opt, arg in opts:
        if opt == '-h' or opt == '--help':
            print('Usage: gpiotest_pi5.py [--gpio_num <num>]')
            sys.exit()
        elif opt == '-g' or opt == '--gpio_num':
            if arg == '17':
                gpio_num = 17
            elif arg == '26':
                gpio_num = 26
            else:
                print('Error: gpio_num must be 17 or 26')
                sys.exit()

    try:
        # Init curses
        myscreen = curses.initscr()
        logwindow = myscreen.subwin(5, 80, 16, 0)
        msgwindow = myscreen.subwin(1, 80, 22, 0)
        termOff()

        # Detect Raspberry Pi model
        RaspiModel, detected_gpio_num = get_pi_model()
        if RaspiModel == "not supported":
            raise RuntimeError('GPIOTEST does not support this version of Raspberry PI.')

        # Set GPIO parameters
        if gpio_num == 0:
            gpio_num = detected_gpio_num

        # Define which GPIO pins to monitor
        if gpio_num == 17:
            gpio_ch = [0, 1, 4, 7, 8, 9, 10, 11, 14, 15, 17, 18, 21, 22, 23, 24, 25]
        else:
            gpio_ch = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27]
        debounce = 200

        # Init vars
        gpio_state = [0 for _ in range(gpio_num)]
        gpio_inout = [0 for _ in range(gpio_num)]
        gpio_pud = [0 for _ in range(gpio_num)]
        on_pause = 0
        log = ['' for _ in range(6)]
        chip = gpiod.Chip("gpiochip4")

        # Init GPIO
        initGpio(1)

        # Main loop
        while True:
            MainScreen()
            CheckKeys()
            time.sleep(0.1)

    except KeyboardInterrupt:
        # In case of keyboard interrupt
        myscreen.addstr(21, 0, "Ctrl-C pressed")
        time.sleep(0.5)
        
    except Exception as e:
        print(f"Error: {e}")

    finally:
        # Reset terminal and clean up
        global stop_monitoring
        stop_monitoring = True
        
        # Join all monitoring threads
        for thread in monitor_threads:
            if thread.is_alive():
                thread.join(1.0)
                
        # Release all GPIO lines
        for line in lines:
            if line:
                try:
                    line.release()
                except:
                    pass
                    
        # Release chip
        if chip:
            del chip
            
        # Reset terminal
        termOn()
        curses.endwin()

if __name__ == "__main__":
    main()