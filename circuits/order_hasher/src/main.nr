// order_hasher: computes the public values of a sealed order with the same functions the
// sealed_order circuit uses (commitment, nullifier, identity leaf, Merkle root), so Python
// never needs its own Poseidon2. Run with `nargo execute`; the outputs are printed.

use order_lib::{identity_leaf, merkle_root, order_commitment, order_nullifier};

fn main(
    side: u8,
    limit: u64,
    size: u64,
    salt: Field,
    trader_secret: Field,
    batch_id: Field,
    path: [Field; 8],
    index_bits: [u1; 8],
) -> pub (Field, Field, Field, Field) {
    let leaf = identity_leaf(trader_secret);
    (
        order_commitment(side, limit, size, salt, trader_secret),
        order_nullifier(trader_secret, batch_id),
        leaf,
        merkle_root(leaf, path, index_bits),
    )
}
