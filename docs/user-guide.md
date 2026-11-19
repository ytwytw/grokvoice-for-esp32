# User guide

This guide describes the v1 controls. Prepare the [firmware](build-and-run.md) and [gateway](gateway.md) first. Live device and Grok operation have not been verified for this extracted source tree. Account-specific permission and service entitlement are required; see the [provider guide](provider.md).

## Talk to Grok

1. On the Voice Preview Edition, turn off mute. When the speaker is idle, say **“Okay Nabu”** or press the center button once.
2. Wait for the listening tone, then start speaking within a few seconds. If you say nothing for about six seconds, the call ends.
3. Listen to the reply. When it finishes, you have **eight seconds** to ask another question. You can speak without repeating the wake word or pressing the button.
4. To end the conversation, press the button once. If you stay silent for the full eight seconds, the call ends on its own.

Speaking during a reply will not interrupt it. To stop a reply early, press the button to end the call. The wake word only starts a call when the device is idle.

## Other controls

| To do this | Use this control |
| --- | --- |
| Start a new topic with a fresh conversation | Press and hold the center button. |
| Change how loud the reply sounds | Turn the volume knob. The knob controls only the speaker. |
| Stop the microphone | Turn on the mute switch. This also ends an active call. |

## Light ring

| Light | Meaning |
| --- | --- |
| Off | Idle and ready. |
| Green | Listening. |
| Purple | Thinking. |
| Blue | Speaking a reply. |
| Orange | An error ended the call. |
| Red | Muted. |
| Blinking red | The gateway has been unreachable for more than about 10 seconds. |
| Amber | Connecting to Wi-Fi. |
| Green bar | Current volume, shown briefly while you turn the knob. |

## Where your audio goes

**On your local network.** When the speaker is connected and unmuted, it sends microphone audio to the Linux gateway, even while idle. The gateway discards idle audio without saving it. Use a trusted local network.

**During a call.** After you start a call, the gateway sends your question and follow-up audio to Grok over the internet. It drops microphone audio while a reply plays. Cloud upload stops when the call ends. Grok's privacy and retention settings apply to audio it receives.

## If a follow-up gets no reply

If you spoke while the reply was playing, wait until it finishes and ask again. If more than eight seconds have passed since it finished, say “Okay Nabu” or press the button, then wait for the tone.
