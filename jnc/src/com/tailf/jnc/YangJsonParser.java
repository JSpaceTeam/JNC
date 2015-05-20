package com.tailf.jnc;


import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.core.JsonToken;
import org.xml.sax.Attributes;
import org.xml.sax.SAXException;
import org.xml.sax.helpers.AttributesImpl;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;

/**
 * Yang Jason Parser for parsing json and converting to Element
 *
 */
public class YangJsonParser {


    private final ElementHandler elementHandler = new ElementHandler();

    private final Attributes attr  = new AttributesImpl();
    /**
     * Read a json file and convert into Element. If prefixMap has the default namespace and prefix then
     * the element returned will be of type YangElement if the generated files exist
     *
     * @param filename
     * @param prefixMap
     * @return
     * @throws JNCException
     */
    public final Element readFile(String filename, PrefixMap prefixMap) throws JNCException {
        Element top = null;
        try (final JsonParser jp = YangJsonFactory.jsonFactory().createParser(new File(filename))) {
            if (jp.nextToken() != JsonToken.START_OBJECT) {
                throw new JNCException(JNCException.PARSER_ERROR, "Expected data to start with an Object");
            }
            if (prefixMap != null) {
                for (int i=0;i<prefixMap.size();i++) {

                }
            }
            parseObject(jp, getAndUpdateNamespace(prefixMap));
            top = elementHandler.top;
        } catch (Exception e) {
            throw new JNCException(JNCException.PARSER_ERROR, "Failed to parse Json error: " + e);
        }
        return top;
    }

    /**
     * Parse a JSON input stream into Element.
     * If prefix map is set and schema is registered then schema aware YangElement will be returned
     * @param is
     * @param prefixMap
     * @return
     * @throws JNCException
     */
    public final Element parse(InputStream is, PrefixMap prefixMap) throws JNCException {
        Element top = null;
        try (final JsonParser jp = YangJsonFactory.jsonFactory().createParser(is)) {
            if (jp.nextToken() != JsonToken.START_OBJECT) {
                throw new JNCException(JNCException.PARSER_ERROR, "Expected data to start with an Object");
            }
            parseObject(jp, getAndUpdateNamespace(prefixMap));
            top = elementHandler.top;
        } catch (Exception e) {
            e.printStackTrace();
            throw new JNCException(JNCException.PARSER_ERROR, "Failed to parse Json error: " + e);

        }
        return top;
    }

    /**
     * Parse a json string and convert to Element. If prefix map is set and the Schema is enabled returned type
     * will be YangElement
     *
     * @param jsonString
     * @param prefixMap
     * @return
     * @throws JNCException
     */
    public final Element parse(String jsonString, PrefixMap prefixMap) throws JNCException {
        final ByteArrayInputStream bis = new ByteArrayInputStream(jsonString.getBytes());
        return parse(bis, prefixMap);
    }


    /**
     * Parse a json string and convert to Element. If prefix map is set and the Schema is enabled returned type
     * will be YangElement
     *
     * @param jsonString
     * @param prefixMap
     * @return
     * @throws JNCException
     */
    public final Element parse(String containerName, String jsonString, PrefixMap prefixMap) throws JNCException {
        String fullStr = "{\"" + containerName + "\":" + jsonString + "}";
        final ByteArrayInputStream bis = new ByteArrayInputStream(fullStr.getBytes());
        return parse(bis, prefixMap);
    }


    private void parseObject(final JsonParser jp, final String nameSpace) throws IOException, SAXException {
        while(jp.nextToken() != JsonToken.END_OBJECT) {
            String name = jp.getCurrentName();
            if (name != null) {
                //Just a JSON start object skip it

                JsonToken jsonToken = jp.nextToken();

                if (jsonToken == JsonToken.START_ARRAY) {
                    processArray(jp, nameSpace, name);
                    continue;
                }
                elementHandler.startElement(nameSpace, name, name, attr);
                if (jsonToken.isScalarValue()) {
                    elementHandler.characters(jp.getTextCharacters(), 0, jp.getTextLength());
                }
                if (jsonToken == JsonToken.START_OBJECT) {
                    parseObject(jp, nameSpace);
                }
                elementHandler.endElement(nameSpace, name, name);
            } else {
                jp.nextToken();
            }
        }
    }

    /**
     * process json array. In case of Json an array is presented as  {{{ "abc": [{"test": 1},{"test":2}] }}} This needs
     * to be converted to a xml sax events so end and start needs to be pushed for every element in an array
     * @param jp
     * @param nameSpace
     * @param name
     * @throws IOException
     * @throws SAXException
     */
    private void processArray(final JsonParser jp, final String nameSpace, final String name) throws IOException, SAXException {
        while (jp.nextToken() != JsonToken.END_ARRAY) {
            elementHandler.startElement(nameSpace, name, name, attr);
            String text = jp.getText();
            if(!text.startsWith("{"))
                this.elementHandler.leafValue = text;
            else
                parseObject(jp, nameSpace);
            elementHandler.endElement(nameSpace, name, name);
        }
    }


    private String getAndUpdateNamespace(PrefixMap prefixes) {
        String nameSpace = "";
        if (prefixes != null) {
            for (int i=0;i<prefixes.size();i++) {
                Prefix prefix = prefixes.get(i);
                if (prefix.qName != null && prefix.qName.split(":").length == 1) {
                    nameSpace = prefix.value;
                }
                if (prefix.qName.indexOf(":") > 0) {
                    elementHandler.startPrefixMapping(prefix.qName.replace("xmlns:", ""), prefix.value);
                } else {
                    elementHandler.startPrefixMapping(prefix.qName.replace("xmlns", ""), prefix.value);
                }
            }
        }
        return nameSpace;
    }

}
