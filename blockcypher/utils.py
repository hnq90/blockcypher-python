import re

from hashlib import sha256

from .constants import (SHA_COINS, SCRYPT_COINS, COIN_SYMBOL_LIST,
    COIN_SYMBOL_MAPPINGS, FIRST4_MKEY_CS_MAPPINGS_UPPER)

from bitcoin.main import safe_from_hex
from bitcoin.transaction import deserialize, script_to_address


SATOSHIS_PER_BTC = 10**8
SATOSHIS_PER_MILLIBITCOIN = 10**5
SATOSHIS_PER_BIT = 10**2

HEX_CHARS_RE = re.compile('^[0-9a-f]*$')


UNIT_CHOICES = ['btc', 'mbtc', 'bit', 'satoshi']


def format_output(num, output_type):
    if output_type == 'btc':
        return '{0:,.8f}'.format(num)
    elif output_type == 'mbtc':
        return '{0:,.5f}'.format(num)
    elif output_type == 'bit':
        return '{0:,.2f}'.format(num)
    elif output_type == 'satoshi':
        return '{:,}'.format(int(num))
    else:
        raise Exception('Invalid Unit Choice: %s' % output_type)


def to_satoshis(input_quantity, input_type):
    ''' convert to satoshis, no rounding '''
    assert input_type in UNIT_CHOICES, input_type

    # convert to satoshis
    if input_type == 'btc':
        satoshis = float(input_quantity) * float(SATOSHIS_PER_BTC)
    elif input_type == 'mbtc':
        satoshis = float(input_quantity) * float(SATOSHIS_PER_MILLIBITCOIN)
    elif input_type == 'bit':
        satoshis = float(input_quantity) * float(SATOSHIS_PER_BIT)
    elif input_type == 'satoshi':
        satoshis = input_quantity
    else:
        raise Exception('Invalid Unit Choice: %s' % input_type)

    return int(satoshis)


def from_satoshis(input_satoshis, output_type):
    # convert to output_type,
    if output_type == 'btc':
        return input_satoshis / float(SATOSHIS_PER_BTC)
    elif output_type == 'mbtc':
        return input_satoshis / float(SATOSHIS_PER_MILLIBITCOIN)
    elif output_type == 'bit':
        return input_satoshis / float(SATOSHIS_PER_BIT)
    elif output_type == 'satoshi':
        return int(input_satoshis)
    else:
        raise Exception('Invalid Unit Choice: %s' % output_type)


def get_curr_symbol(coin_symbol, output_type):
    if output_type == 'btc':
        return COIN_SYMBOL_MAPPINGS[coin_symbol]['currency_abbrev']
    elif output_type == 'mbtc':
        return 'm%s' % COIN_SYMBOL_MAPPINGS[coin_symbol]['currency_abbrev']
    elif output_type == 'bit':
        return 'bits'
    elif output_type == 'satoshi':
        return 'satoshis'
    else:
        raise Exception('Invalid Unit Choice: %s' % output_type)


def format_crypto_units(input_quantity, input_type, output_type, coin_symbol=None, print_cs=False):
    '''
    Take an input like 11002343 satoshis and convert it to another unit (e.g. BTC) and format it with appropriate units

    if coin_symbol is supplied and print_cs == True then the units will be added (e.g. BTC or satoshis)

    Requires python >= 2.7
    '''
    assert input_type in UNIT_CHOICES, input_type
    assert output_type in UNIT_CHOICES, output_type
    if print_cs:
        assert is_valid_coin_symbol(coin_symbol=coin_symbol), coin_symbol

    satoshis_float = to_satoshis(input_quantity=input_quantity, input_type=input_type)

    output_quantity = from_satoshis(
            input_satoshis=satoshis_float,
            output_type=output_type,
            )

    # add thousands separator and appropriate # of decimals
    output_quantity_formatted = format_output(num=output_quantity, output_type=output_type)

    if print_cs:
        output_quantity_formatted += ' ' + get_curr_symbol(
                coin_symbol=coin_symbol,
                output_type=output_type,
                )

    return output_quantity_formatted


def lib_can_deserialize_cs(coin_symbol):
    '''
    Be sure that this library can deserialize a transaction for this coin

    This is not a limitation of blockcypher's service but this library's
    ability to deserialize a transaction hex to json.
    '''
    assert is_valid_coin_symbol(coin_symbol), coin_symbol
    if 'vbyte_pubkey' in COIN_SYMBOL_MAPPINGS[coin_symbol]:
        return True
    else:
        return False


def get_txn_outputs(raw_tx_hex, output_addr_list, coin_symbol):
    '''
    Used to verify a transaction hex does what's expected of it.

    Must supply a list of output addresses so that the library can try to
    convert from script to address using both pubkey and script.

    Returns a list of the following form:
        [{'value': 12345, 'address': '1abc...'}, ...]

    Uses @vbuterin's decoding methods.
    '''
    # Defensive checks:
    err_msg = 'Library not able to parse %s transactions' % coin_symbol
    assert lib_can_deserialize_cs(coin_symbol), err_msg
    assert type(output_addr_list) in (list, tuple)
    for output_addr in output_addr_list:
        assert is_valid_address(output_addr), output_addr

    outputs = []
    deserialized_tx = deserialize(str(raw_tx_hex))
    for out in deserialized_tx.get('outs', []):
        output_addr_set = set(output_addr_list)  # speed optimization

        # determine if the address is a pubkey address or a script address
        pubkey_addr = script_to_address(out['script'],
                vbyte=COIN_SYMBOL_MAPPINGS[coin_symbol]['vbyte_pubkey'])
        script_addr = script_to_address(out['script'],
                vbyte=COIN_SYMBOL_MAPPINGS[coin_symbol]['vbyte_script'])
        if pubkey_addr in output_addr_set:
            address = pubkey_addr
        elif script_addr in output_addr_set:
            address = script_addr
        else:
            raise Exception('Script %s Does Not Contain a Valid Output Address: %s' % (
                out['script'],
                output_addr_set,
                ))

        output = {
                'value': out['value'],
                'address': address,
                }
        outputs.append(output)
    return outputs


def compress_txn_outputs(txn_outputs):
    '''
    Take a list of txn ouputs (from get_txn_outputs) and compress it to the
    sum of satoshis sent to each address in a dictionary.

    Returns a dict of the following form:
        {'1abc...': 12345, '1def': 54321, ...}
    '''
    result_dict = {}
    for txn_output in txn_outputs:
        if txn_output['address'] in result_dict:
            result_dict[txn_output['address']] += txn_output['value']
        else:
            result_dict[txn_output['address']] = txn_output['value']
    return result_dict


def get_txn_outputs_dict(raw_tx_hex, output_addr_list, coin_symbol):
    return compress_txn_outputs(
            txn_outputs=get_txn_outputs(
                raw_tx_hex=raw_tx_hex,
                output_addr_list=output_addr_list,
                coin_symbol=coin_symbol,
                )
            )


def double_sha256(hex_string):
    '''
    Double sha256. Example:
    Input:
      '0100000001294ea156f83627e196b31f8c70597c3b38851c174259bca7c80888ca422c4db8010000001976a914869441d5dc3befb911151d60501d85683483aa9d88acffffffff020a000000000000001976a914f93d302789520e8ca07affb76d4ba4b74ca3b3e688ac3c215200000000001976a914869441d5dc3befb911151d60501d85683483aa9d88ac0000000001000000'
    Output:
      'e147a7e260afbb779db8acd56888aab66232d6136f60a11aeb4c0bb4efacb33c'
    Uses @vbuterin's safe_from_hex for python2/3 compatibility
    '''
    return sha256(sha256(safe_from_hex(hex_string)).digest()).hexdigest()


def get_blockcypher_walletname_from_mpub(mpub, subchain_indices=[]):
    '''
    Blockcypher limits wallet names to 25 chars.

    Hash the master pubkey (with subchain indexes) and take the first 25 chars.

    Hackey determinstic method for naming.
    '''

    #  http://stackoverflow.com/a/19877309/1754586
    mpub = mpub.encode('utf-8')

    if subchain_indices:
        mpub += ','.join([str(x) for x in subchain_indices]).encode('utf-8')
    return sha256(mpub).hexdigest()[:25]


def btc_to_satoshis(btc):
    return int(float(btc) * SATOSHIS_PER_BTC)


def satoshis_to_btc(satoshis):
    return float(satoshis) / float(SATOSHIS_PER_BTC)


def satoshis_to_btc_rounded(satoshis, decimals=4):
    btc = satoshis_to_btc(satoshis)
    if decimals:
        return round(btc, decimals)
    else:
        return btc


def uses_only_hash_chars(string):
    return HEX_CHARS_RE.match(string)


def is_valid_hash(string):
    string = str(string)  # in case of being passed an int
    return len(string.strip()) == 64 and uses_only_hash_chars(string)


# Blocks #

def is_valid_block_num(block_num):
    try:
        bn_as_int = int(block_num)
    except:
        return False

    # hackey approximation
    return 0 <= bn_as_int <= 10**8


def is_valid_sha_block_hash(block_hash):
    return is_valid_hash(block_hash) and block_hash[:5] == '00000'


def is_valid_scrypt_block_hash(block_hash):
    " Unfortunately this is indistiguishable from a regular hash "
    return is_valid_hash(block_hash)


def is_valid_sha_block_representation(block_representation):
    return is_valid_block_num(block_representation) or is_valid_sha_block_hash(block_representation)


def is_valid_scrypt_block_representation(block_representation):
    return is_valid_block_num(block_representation) or is_valid_scrypt_block_hash(block_representation)


def is_valid_bcy_block_representation(block_representation):
    block_representation = str(block_representation)
    # TODO: more specific rules
    if is_valid_block_num(block_representation):
        return True
    elif is_valid_hash(block_representation):
        if block_representation[:4] == '0000':
            return True
    return False


def is_valid_block_representation(block_representation, coin_symbol):
    # TODO: make handling of each coin more unique
    assert is_valid_coin_symbol(coin_symbol)

    # defensive checks
    if coin_symbol in SHA_COINS:
        if coin_symbol == 'bcy':
            return is_valid_bcy_block_representation(block_representation)
        else:
            return is_valid_sha_block_representation(block_representation)
    elif coin_symbol in SCRYPT_COINS:
        return is_valid_scrypt_block_representation(block_representation)


# Coin Symbol #

def is_valid_coin_symbol(coin_symbol):
    return coin_symbol in COIN_SYMBOL_LIST


def coin_symbol_from_mkey(mkey):
    '''
    Take a master private or public extended key in standard format
    (e.g. xpriv123..., xpub123..., tprv123..., etc) and infer the coin symbol

    Case insensitive to be forgiving of user error
    '''
    return FIRST4_MKEY_CS_MAPPINGS_UPPER.get(mkey[:4].upper())

# Addresses #

# Copied 2014-09-24 from http://rosettacode.org/wiki/Bitcoin/address_validation#Python

DIGITS58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'


# From https://github.com/nederhoed/python-bitcoinaddress/blob/cb483b875d4467ef798d178e232b357a153bed72/bitcoinaddress/validation.py
def _long_to_bytes(n, length, byteorder):
    """Convert a long to a bytestring
    For use in python version prior to 3.2
    Source:
    http://bugs.python.org/issue16580#msg177208
    """
    if byteorder == 'little':
        indexes = range(length)
    else:
        indexes = reversed(range(length))
    return bytearray((n >> i * 8) & 0xff for i in indexes)


def decode_base58(bc, length):
    n = 0
    for char in bc:
        n = n * 58 + DIGITS58.index(char)
    try:
        return n.to_bytes(length, 'big')
    except AttributeError:
        return _long_to_bytes(n, length, 'big')


def crypto_address_valid(bc):
    bcbytes = decode_base58(bc, 25)
    return bcbytes[-4:] == sha256(sha256(bcbytes[:-4]).digest()).digest()[:4]


def is_valid_address(b58_address):
    try:
        return crypto_address_valid(b58_address)
    except:
        # handle edge cases like an address too long to decode
        return False


def is_valid_address_for_coinsymbol(b58_address, coin_symbol):
    '''
    Is an address both valid *and* start with the correct character
    for its coin symbol (chain/network)
    '''
    assert is_valid_coin_symbol(coin_symbol)

    if b58_address[0] in COIN_SYMBOL_MAPPINGS[coin_symbol]['address_first_char_list']:
        if is_valid_address(b58_address):
            return True
    return False
