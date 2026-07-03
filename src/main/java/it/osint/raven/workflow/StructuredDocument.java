package it.osint.raven.workflow;

/**
 * Marker contract for documents produced by parsers and consumed by workflow nodes.
 * <p>
 * Implementations can represent articles, social messages, PDF documents or any
 * other structured OSINT document without binding the workflow model to a single
 * DTO type.
 */
public interface StructuredDocument {
}
