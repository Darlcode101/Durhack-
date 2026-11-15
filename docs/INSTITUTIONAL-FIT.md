# Marshall Wace: answering "New Worlds"

**Main audience (Jonah, 2026-11-14): Marshall Wace**, the hedge fund. Their DurHack challenge, from the opening ceremony slides:

> **New Worlds.** Make a project that explores the idea of New Worlds. Build something that opens a door to the unexplored, whether that's new data, ideas or something novel no one has seen before. Interpret the theme however you think best captures the spirit of this idea. They want to see **creativity, technical complexity and good presentation**.

## The New Worlds pitch (Jonah's framing)

> The past few months have been the **worst ever for cyber security**, especially the Binance attack. In this **new AI-accelerated world** we need **peace of mind**. We are introducing a **future-proof, quantum-resistant** system that is **fully available to newer users**, who don't need to understand how it works, because there are **no inputs whatsoever**. In its base form it is an **unsuspecting connector** to the transfer application, **not explicitly listed**: the port just waits for "the key" and **doesn't say where it comes from**, which leaves a physical attacker very confused. It is built to be a **new kind of technology**.

How each line holds up, so we can say it without overclaiming:

| Line | What is true | Say it like this |
|---|---|---|
| **Worst months for cyber security, Binance** | Confirmed: 29 October 2026, about $6.3 to 6.4 billion, through a compromised laptop and an internal AI tool reaching the signing service ([PRIOR-ART.md](PRIOR-ART.md#facts-used-in-the-pitch-checked)) | "An attacker used an AI tool and a laptop to make Binance's own signer approve it. Nobody was asked." |
| **AI-accelerated world, peace of mind** | The Binance route went through an AI tool; AI also makes phishing and impersonation cheaper | "Approvals have to be something an AI-assisted attacker can't talk, click or script their way through" |
| **Future-proof, quantum-resistant** | The **approval signatures** are ML-DSA-65 (NIST FIPS 204), with an SLH-DSA offline root planned. The YubiKey part is still classical, which is why ML-DSA is required alongside it. We haven't had it reviewed | "Approvals are signed with a NIST post-quantum algorithm, so a future quantum computer can't forge them." Not "everything is quantum-proof" |
| **No inputs, fine for new users** | True for the **normal case** (a click you were going to make). An uncertain hand returns a step-up result for the customer's system to handle | "Nothing to learn and nothing to do in the normal case" |
| **Encrypts in one of the most secure ways** | Mostly it **signs** rather than encrypts. The signing key is wrapped with AES-256 under a YubiKey secret; links use TLS | "The key can't be used without the YubiKey, the right hand and the click", not "it's encrypted in the most secure way" |
| **Unsuspecting connector, not listed** | Literally true on the computer: the device has **no USB connection to the laptop**, so it doesn't appear as a device or driver; only the ordinary mouse does. At the transfer application, a generic approval endpoint accepts a **valid signed envelope from an opaque signer ID** and says nothing about what produced it ([STEALTH-APPROVAL.md](STEALTH-APPROVAL.md#misdirection-what-an-attacker-sees-in-the-logs)). **One hole:** the UNO Q joins Wi-Fi, so a client appears on the network with a name and MAC. Use a neutral hostname, a separate network, and don't claim it is invisible | "Nothing on the machine lists it, and the port doesn't say where its key comes from" |
| **Confuses a physical attacker** | Misdirection helps against someone who doesn't know the design; it fails against an insider or anyone who opens the mouse | Say it as an extra layer on the crypto, not the protection |
| **A completely new technology** | **Not defensible as worded.** Every part has prior art ([PRIOR-ART.md](PRIOR-ART.md)). We found no product or paper combining all of them | "**To our knowledge, a new combination** that none of the existing products or papers we found put together" |

**The defensible one-liner:** *In a world where AI helps attackers steal billions without breaking a single key, YuDuino gives approvals peace of mind: a post-quantum-signed, accountable approval that needs no input, no screen to trust and no training, hidden in a mouse nobody suspects.*
