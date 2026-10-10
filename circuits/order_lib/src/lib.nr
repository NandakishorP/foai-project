// order_lib: the hashes shared by the sealed_order circuit and the order_hasher helper,
// so the prover's public inputs and the circuit's checks use literally the same code.

use poseidon::poseidon2::Poseidon2;

pub global DEPTH: u32 = 8; // identity Merkle tree depth: up to 256 registered identities

pub fn order_commitment(side: u8, limit: u64, size: u64, salt: Field, trader_secret: Field) -> Field {
    Poseidon2::hash([side as Field, limit as Field, size as Field, salt, trader_secret], 5)
}

pub fn order_nullifier(trader_secret: Field, batch_id: Field) -> Field {
    Poseidon2::hash([trader_secret, batch_id], 2)
}

pub fn identity_leaf(trader_secret: Field) -> Field {
    Poseidon2::hash([trader_secret], 1)
}

pub fn merkle_root(leaf: Field, path: [Field; DEPTH], index_bits: [u1; DEPTH]) -> Field {
    let mut node = leaf;
    for i in 0..DEPTH {
        node = if index_bits[i] == 0 {
            Poseidon2::hash([node, path[i]], 2)
        } else {
            Poseidon2::hash([path[i], node], 2)
        };
    }
    node
}
