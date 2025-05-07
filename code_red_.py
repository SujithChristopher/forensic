from twilio.rest import Client
import time
import toml


# import secrets
_pth = '/home/rpi2/Documents/secrets.toml'

secrets = toml.load(_pth)['secrets']

class SendMessage:
    def __init__(self):
        self.account_sid = secrets['account_sid']
        self.auth_token = secrets['auth_token']
        self.client = Client(self.account_sid, self.auth_token)
        
    def send_message(self, message = "NO POWER"):
        self.message = self.client.messages.create(
            from_="+17752274344", body=message, to="+918489878428"
        )

    def alert_people(self):
        call_numbers = ["+918489878428", "+919007424748"]

        for _c in call_numbers:
            call = self.client.calls.create(
                from_="+17752274344",
                to=_c,
                url="http://demo.twilio.com/docs/voice.xml",
            )
            print(call.sid)
            time.sleep(2)
