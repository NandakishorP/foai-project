// sealed_order: proves a sealed order is valid and solvent without revealing it (SPEC section 5, DECISIONS D-002/D-046).
//
// Public:  commitment, escrow, batch_id, nullifier, identity_root
// Private: side, limit, size, salt, trader_secret, Merkle path of the trader's identity
//
// The proof convinces the batch auction, at commit time, that:
//   1. the commitment opens to a well-formed buy order (side in {YES, NO}, 0 < limit < 1, size > 0);
//   2. the order is solvent: its worst-case cost limit * size is covered by the posted escrow;
//   3. the trader is a registered identity (Merkle membership of Poseidon2(secret)), without saying which;
//   4. the nullifier is Poseidon2(secret, batch_id): one order per registered identity per batch.
//
// Units: limit in millionths (1_000_000 = a price of 1), size and escrow in 6-decimal units,
// so worst-case cost (in 6-decimal units) = limit * size / 1_000_000.
// `limit` is the most the trader pays per share of the side it buys, so the worst case is
// limit * size for both sides. (SPEC section 5 writes it with a YES-price limit: limit*size for YES,
// (1 - limit)*size for NO. That is the same constraint.)

use order_lib::{DEPTH, identity_leaf, merkle_root, order_commitment, order_nullifier};

global PRICE_ONE: u64 = 1_000_000;

fn main(
    side: u8,
    limit: u64,
    size: u64,
    salt: Field,
    trader_secret: Field,
    path: [Field; DEPTH],
    index_bits: [u1; DEPTH],
    commitment: pub Field,
    escrow: pub u64,
    batch_id: pub Field,
    nullifier: pub Field,
    identity_root: pub Field,
) {
    // 1. well-formed order
    assert(side <= 1, "side must be 0 (YES) or 1 (NO)");
    assert(limit > 0, "limit must be positive");
    assert(limit < PRICE_ONE, "limit must be below 1");
    assert(size > 0, "size must be positive");
    // 2. solvent: limit * size <= escrow * 1e6 (u128 so the product cannot overflow)
    assert((limit as u128) * (size as u128) <= (escrow as u128) * (PRICE_ONE as u128), "escrow too small");
    // the commitment opens to exactly this order
    assert(commitment == order_commitment(side, limit, size, salt, trader_secret), "bad commitment");
    // 3. registered identity
    assert(merkle_root(identity_leaf(trader_secret), path, index_bits) == identity_root, "not a registered identity");
    // 4. one order per identity per batch
    assert(nullifier == order_nullifier(trader_secret, batch_id), "bad nullifier");
}

// ------------------------------------------------------------------- tests

struct Case {
    side: u8,
    limit: u64,
    size: u64,
    salt: Field,
    secret: Field,
    path: [Field; DEPTH],
    bits: [u1; DEPTH],
    commitment: Field,
    escrow: u64,
    batch_id: Field,
    nullifier: Field,
    root: Field,
}

// A valid order: buy 20 YES at up to 0.6, escrow 25 USDC (worst case 12), identity at leaf index 5.
fn valid_case() -> Case {
    let (side, limit, size, salt, secret, batch_id) = (0, 600_000, 20_000_000, 42, 1234567, 7);
    let mut path = [0; DEPTH];
    for i in 0..DEPTH {
        path[i] = (i as Field) + 1000;
    }
    let bits: [u1; DEPTH] = [1, 0, 1, 0, 0, 0, 0, 0];
    Case {
        side, limit, size, salt, secret, path, bits,
        commitment: order_commitment(side, limit, size, salt, secret),
        escrow: 25_000_000,
        batch_id,
        nullifier: order_nullifier(secret, batch_id),
        root: merkle_root(identity_leaf(secret), path, bits),
    }
}

fn run(c: Case) {
    main(c.side, c.limit, c.size, c.salt, c.secret, c.path, c.bits, c.commitment, c.escrow, c.batch_id, c.nullifier, c.root);
}

#[test]
fn test_valid_order() {
    run(valid_case());
}

#[test]
fn test_valid_no_order_at_exact_escrow() {
    let mut c = valid_case();
    c.side = 1;
    c.limit = 500_000;
    c.size = 50_000_000; // worst case 25 USDC = escrow exactly
    c.commitment = order_commitment(c.side, c.limit, c.size, c.salt, c.secret);
    run(c);
}

#[test(should_fail_with = "side must be 0 (YES) or 1 (NO)")]
fn test_bad_side() {
    let mut c = valid_case();
    c.side = 2;
    c.commitment = order_commitment(c.side, c.limit, c.size, c.salt, c.secret);
    run(c);
}

#[test(should_fail_with = "limit must be positive")]
fn test_zero_limit() {
    let mut c = valid_case();
    c.limit = 0;
    run(c);
}

#[test(should_fail_with = "limit must be below 1")]
fn test_limit_of_one() {
    let mut c = valid_case();
    c.limit = PRICE_ONE;
    run(c);
}

#[test(should_fail_with = "size must be positive")]
fn test_zero_size() {
    let mut c = valid_case();
    c.size = 0;
    run(c);
}

#[test(should_fail_with = "escrow too small")]
fn test_insolvent_order() {
    let mut c = valid_case();
    c.escrow = 5_000_000; // worst case 12 USDC > 5
    run(c);
}

#[test(should_fail_with = "bad commitment")]
fn test_commitment_to_a_different_order() {
    let mut c = valid_case();
    c.size = 10_000_000; // prove for a smaller order than committed
    run(c);
}

#[test(should_fail_with = "not a registered identity")]
fn test_unregistered_identity() {
    let mut c = valid_case();
    c.root = c.root + 1;
    run(c);
}

#[test(should_fail_with = "bad nullifier")]
fn test_nullifier_from_another_batch() {
    let mut c = valid_case();
    c.nullifier = order_nullifier(c.secret, c.batch_id + 1);
    run(c);
}
