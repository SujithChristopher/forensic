from twilio.rest import Client
import time
import toml


# import secrets
_pth = '/home/rpi2/Documents/secrets.toml'
_numbers_pth = '/home/rpi2/Documents/forensic/numbers.toml'

secrets = toml.load(_pth)['secrets']
numbers_to_send = toml.load(_numbers_pth)['people']['phone_numbers']
print(numbers_to_send)

class SendMessage:
    def __init__(self, numbers = None):
        self.account_sid = secrets['account_sid']
        self.auth_token = secrets['auth_token']
        self.client = Client(self.account_sid, self.auth_token)
        
        self.numbers = numbers
        if self.numbers is None:
            self.numbers = numbers_to_send
        else:
            self.numbers = numbers
        
    def send_message(self, message = "NO POWER"):
        for _n in self.numbers:
            self.client.messages.create(
                from_="+17752274344", body=message, to=_n
            )


    def alert_people(self):
        
        for _n in self.numbers:
            call = self.client.calls.create(
                from_="+17752274344",
                to=_n,
                url="http://demo.twilio.com/docs/voice.xml",
            )
            print(call.sid)
            time.sleep(2)

if __name__ == "__main__":
    # List of numbers to send the message to
    numbers = [
        "+918489878428",
    ]
    send_message = SendMessage(numbers=numbers)
    send_message.send_message()
    send_message.alert_people()