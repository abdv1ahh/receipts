-- Migration 037: a handle stops being editable the moment something is published under it.
--
-- Registration is open from this change onward (Part B), which turns a handle from an internal
-- label into a public identity a stranger is asked to trust. Three things now depend on the exact
-- string: the `/r/{handle}` link a caller shares, the share card rendered from it, and the
-- `/record?handle=` URL every reader was given. None of them can be recalled once posted.
--
-- THE CHAIN WOULD NOT CATCH THIS, WHICH IS THE WHOLE REASON THIS TRIGGER EXISTS.
-- `chain.SEALED_FIELDS` hashes `caller_id`, not the handle — deliberately, so that a display
-- identity can be corrected without invalidating 473 sealed rows. The consequence is that renaming
-- a caller leaves every hash verifying perfectly while every shared link now points at a record
-- built by someone the reader never agreed to follow. A record accumulated under one identity
-- could be re-badged under another and `verify_chain` would still return intact.
--
-- So the seal protects what was SAID and this protects WHO SAID IT. Neither substitutes for the
-- other, and this one lives in the database for the same reason the append-only trigger does: it
-- has to bind the admin tool nobody has written yet and the psql session someone opens at 2am.
--
-- Note what it deliberately allows: renaming a caller who has published NOTHING. Someone who
-- claims a handle, sees a typo, and fixes it before publishing has broken no link and misled
-- nobody. And `display_name`, `bio` and `audience_url` stay editable forever — a display name is
-- not an address, and a caller who changes employer should not have to abandon their record.
CREATE OR REPLACE FUNCTION callers_handle_immutable() RETURNS trigger AS $$
BEGIN
    IF OLD.handle IS DISTINCT FROM NEW.handle
       AND EXISTS (SELECT 1 FROM calls WHERE caller_id = OLD.id) THEN
        RAISE EXCEPTION 'a handle cannot change once a call has been published under it';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER callers_handle_immutable_trg
    BEFORE UPDATE ON callers
    FOR EACH ROW EXECUTE FUNCTION callers_handle_immutable();

INSERT INTO schema_migrations (version) VALUES (37);
